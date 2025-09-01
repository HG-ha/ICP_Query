import yaml

try:
    class Config:
        def __init__(self, **kwargs):
            for key, value in kwargs.items():
                # 如果值是字典，则递归转换为对象
                if isinstance(value, dict):
                    value = Config(**value)
                setattr(self, key, value)

        def __repr__(self):
            return str(self.__dict__)
        
        def __getattr__(self, name):
            return None

    def load_config(file_path):
        with open(file_path, 'r', encoding='utf-8') as file:
            data = yaml.safe_load(file)

        return Config(**data)

    config = load_config('config.yml')
except:
    print("加载配置文件失败")
    import sys
    sys.exit()