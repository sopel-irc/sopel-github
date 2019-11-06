# coding=utf8
"""
webhook.py - Sopel GitHub Module
Copyright 2015 Max Gurela
Copyright 2019 dgw, Rusty Bower

 _______ __ __   __           __
|     __|__|  |_|  |--.--.--.|  |--.
|    |  |  |   _|     |  |  ||  _  |
|_______|__|____|__|__|_____||_____|
 ________         __     __                 __
|  |  |  |.-----.|  |--.|  |--.-----.-----.|  |--.-----.
|  |  |  ||  -__||  _  ||     |  _  |  _  ||    <|__ --|
|________||_____||_____||__|__|_____|_____||__|__|_____|

"""
from sqlalchemy.exc import OperationalError, SQLAlchemyError
from sqlalchemy.orm import scoped_session, sessionmaker


def get_db_session(bot):
    try:
        engine = bot.db.connect()
    except OperationalError:
        print("OperationalError: Unable to connect to database.")
        raise

    return scoped_session(sessionmaker(bind=engine))
