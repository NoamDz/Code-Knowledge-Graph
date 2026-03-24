import logging
from config import Config
from record_handler import RecordHandler
from error_handler import ErrorHandler

def main():
    config = Config()
    handler = RecordHandler(config)
    handler.run()

if __name__ == "__main__":
    main()
