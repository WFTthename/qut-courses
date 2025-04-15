import scrapy
from scrapy_splash import SplashRequest
import json
import os
import logging
from scrapy.utils.log import configure_logging

class UnitSpider(scrapy.Spider):
    name = "unit_spider"
    allowed_domains = ["qut.edu.au", "localhost"]
    custom_settings = {
        'LOG_LEVEL': 'DEBUG',
        'LOG_FILE': 'spider_debug.log',
        'LOG_FORMAT': '%(asctime)s [%(name)s] %(levelname)s: %(message)s'
    }

    # Splash's Lua script
    lua_script = """
    function main(splash, args)
        splash:set_user_agent('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36')
        assert(splash:go(args.url))
        splash:wait(2)
        return {
            html = splash:html(),
        }
    end
    """
    
    def __init__(self, *args, **kwargs):
        super(UnitSpider, self).__init__(*args, **kwargs)
        self.logger.info("Spider initialization started")
        
        self.all_units = []
        
        try:
            # Use correct relative path
            current_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
            units_file = os.path.join(current_dir, 'units.txt')
            
            with open(units_file, 'r') as f:
                unit_codes = [line.strip() for line in f if line.strip()]
                self.start_urls = [f"https://www.qut.edu.au/study/unit?unitCode={code}" 
                                 for code in unit_codes]
                self.logger.info(f"Found unit codes: {unit_codes}")
                self.logger.info(f"Start URLs: {self.start_urls}")
        except Exception as e:
            self.logger.error(f"Error reading units.txt: {str(e)}")
            self.logger.error(f"Current directory: {os.getcwd()}")
            self.logger.error(f"File path attempted: {units_file}")
            self.start_urls = []

    def start_requests(self):
        self.logger.info("Starting to send requests")
        for url in self.start_urls:
            self.logger.debug(f"Preparing to request URL: {url}")
            yield SplashRequest(
                url,
                self.parse,
                endpoint='execute',
                args={
                    'lua_source': self.lua_script,
                    'wait': 2,
                }
            )

    def clean_prerequisites(self, prerequisites):
        if not prerequisites:
            return None
        prerequisites = prerequisites.strip()
        # If only contains brackets or other meaningless characters, return None
        if prerequisites in ['(', ')', '( )', '()'] or len(prerequisites) <= 2:
            return None
        # If starts with "or", remove the leading "or"
        if prerequisites.startswith('or '):
            prerequisites = prerequisites[3:].strip()
        # If ends with a bracket and has no opening bracket, remove the ending bracket
        if prerequisites.endswith('(') and '(' not in prerequisites[:-1]:
            prerequisites = prerequisites[:-1].strip()
        return prerequisites if prerequisites else None

    def clean_equivalents(self, equivalents):
        if not equivalents:
            return None
        equivalents = equivalents.strip()
        # If contains the generic message, return None
        if "You can't enrol in this unit if you have completed any of these equivalent units" in equivalents:
            return None
        # Remove extra spaces and separators
        equivalents = [e.strip() for e in equivalents.replace(' and ', ',').split(',')]
        # Filter out empty strings and non-course codes
        equivalents = [e for e in equivalents if e and not e.startswith('You')]
        return equivalents if equivalents else None

    def parse(self, response):
        try:
            # Extract basic information
            unit_info = {
                "unitCode": response.xpath('//dt[contains(text(), "Unit code")]/following-sibling::dd[1]/text()').get(),
                "faculty": response.xpath('//dt[contains(text(), "Faculty")]/following-sibling::dd[1]/text()').get(),
                "school": response.xpath('//dt[contains(text(), "School/Discipline")]/following-sibling::dd[1]/text()').get(),
                "studyArea": response.xpath('//dt[contains(text(), "Study area")]/following-sibling::dd[1]/text()').get(),
                "creditPoints": response.xpath('//dt[contains(text(), "Credit points")]/following-sibling::dd[1]/text()').get(),
                "prerequisites": self.clean_prerequisites(response.xpath('//dt[contains(text(), "Prerequisites")]/following-sibling::dd[1]/text()').get()),
                "equivalents": self.clean_equivalents(response.xpath('//dt[contains(text(), "Equivalents")]/following-sibling::dd[1]/text()').get())
            }
            
            # Extract description information
            description = response.xpath('//div[contains(@class, "unit-description")]/p/text()').get()
            if description:
                unit_info["description"] = description.strip()

            # Clean data
            for key, value in unit_info.items():
                if isinstance(value, str):
                    unit_info[key] = value.strip()
                elif isinstance(value, list):
                    unit_info[key] = [v.strip() for v in value if v.strip()]

            # Convert credit points to integer
            if unit_info.get("creditPoints"):
                try:
                    unit_info["creditPoints"] = int(unit_info["creditPoints"])
                except ValueError:
                    self.logger.warning(f"Could not convert credit points to integer: {unit_info['creditPoints']}")

            # Log success
            self.logger.info(f"Successfully extracted unit info for {unit_info.get('unitCode')}")
            
            # Add to list only if at least one field has a value
            if any(unit_info.values()):
                self.all_units.append(unit_info)
                self.logger.info(f"Added unit info to list: {unit_info.get('unitCode')}")

            return unit_info

        except Exception as e:
            self.logger.error(f"Error parsing unit: {str(e)}")
            return {}

    def parse_unit_outline(self, response):
        unit_info = response.meta.get('unit_info', {})
        
        try:
            # 这里原本是准备解析unit outline的，但当时还没有实现
            pass
            
        except Exception as e:
            self.logger.error(f"Error processing unit outline for {unit_info.get('unit_code')}: {str(e)}")
        
        return unit_info

    def closed(self, reason):
        if self.all_units:
            try:
                # 固定使用项目根目录
                current_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
                output_file = os.path.join(current_dir, 'units.json')
                
                # 读取现有数据（如果文件存在）
                existing_units = {"units": []}
                if os.path.exists(output_file):
                    try:
                        with open(output_file, 'r', encoding='utf-8') as f:
                            existing_units = json.load(f)
                    except json.JSONDecodeError:
                        self.logger.warning(f"Could not parse existing units.json, will create new file")
                
                # 获取现有的unit codes
                existing_codes = {unit.get("unitCode") for unit in existing_units.get("units", [])}
                
                # 只添加新的units
                for unit in self.all_units:
                    if unit.get("unitCode") and unit["unitCode"] not in existing_codes:
                        existing_units.setdefault("units", []).append(unit)
                        existing_codes.add(unit["unitCode"])
                        self.logger.info(f"Added new unit: {unit['unitCode']}")
                
                # 保存更新后的数据
                with open(output_file, 'w', encoding='utf-8') as f:
                    json.dump(existing_units, f, indent=4, ensure_ascii=False)
                self.logger.info(f"Successfully saved {len(existing_units['units'])} units to {output_file}")
                
                # 删除spider目录下的units.json（如果存在）
                spider_dir_json = os.path.join(os.path.dirname(__file__), 'units.json')
                if os.path.exists(spider_dir_json):
                    os.remove(spider_dir_json)
                    self.logger.info(f"Removed duplicate units.json from spider directory")
                    
            except Exception as e:
                self.logger.error(f"Error saving units.json: {str(e)}")
                self.logger.error(f"Current directory: {os.getcwd()}")
                self.logger.error(f"File path attempted: {output_file}")
        else:
            self.logger.warning("No units data collected!")
