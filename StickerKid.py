#! /usr/bin/env python3.6

import logging
import os
import re
import sqlite3
import time

from fuzzywuzzy import fuzz
import telepot
from telepot.loop import MessageLoop
from telepot.delegate import pave_event_space, per_inline_from_id,\
    per_chat_id, create_open
from telepot.namedtuple import InlineQueryResultCachedSticker, \
    InlineQueryResultArticle, InputTextMessageContent

import config

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)


def connect_to_db(db_filename):
    conn = sqlite3.connect(db_filename)
    c = conn.cursor()
    return conn, c


# Inline query handlers

class QueryCounter(telepot.helper.InlineUserHandler, telepot.helper.AnswererMixin):
    def __init__(self, *args, **kwargs):
        super(QueryCounter, self).__init__(*args, **kwargs)
        self._count = 0

    def on_inline_query(self, msg):
        def find_sticker_in_db(user_id, sticker):
            # Connect to db
            conn, c = connect_to_db(config.db_filename)

            # Create the result - list of dicts with matched stickers
            result = list()
            for row in c.execute("SELECT * from stickers WHERE user=?",
                                 (user_id,)):
                ratio = fuzz.partial_ratio(sticker, row[2])
                if ratio > 90:
                    result.append({'ratio': ratio,
                                   'id': row[1],
                                   'name': row[2],
                                   'sticker': row[3]})

            # Close the connection
            conn.close()

            # Return the results
            if result:
                return result
            else:
                return None

        def compute():
            query_id, from_id, query_string = telepot.glance(
                msg, flavor='inline_query'
            )
            logger.info(
                'Inline Query from {:d}: {:s}: {:s}'
                .format(self.id,
                        query_id,
                        query_string)
            )

            self._count += 1

            search_result = find_sticker_in_db(from_id, query_string)

            if search_result:
                articles = list()
                for item in search_result:
                    articles.append(
                        InlineQueryResultCachedSticker(
                                 id=str(item['id']),
                                 sticker_file_id=item['sticker'],
                        )
                    )
            else:
                # If there is no result, send the text message
                articles = [InlineQueryResultArticle(
                    id='abc',
                    title='Sticker not found',
                    input_message_content=InputTextMessageContent(
                        message_text='Sticker not found'
                    )
                )]
            return articles

        self.answerer.answer(msg, compute)


# Private messages handlers

class MessageCounter(telepot.helper.ChatHandler):
    def __init__(self, *args, **kwargs):
        super(MessageCounter, self).__init__(*args, **kwargs)
        self._count = 0
        self.temp_sticker = None

    def on_chat_message(self, msg):
        content_type, chat_type, chat_id = telepot.glance(msg)
        logger.info(msg)

        if telepot.flavor(msg) == 'chat':
            def text_match(text):
                def tester(msg):
                    content_type, chat_type, chat_id = telepot.glance(msg)
                    if content_type == 'text':
                        return text == msg['text']
                    return False
                return tester

            def get_list_of_stickers_from_db(user_id):
                conn, c = connect_to_db(config.db_filename)
                result = list()
                for row in c.execute(
                        "SELECT * from stickers WHERE user=? ORDER BY id",
                        (user_id,)
                ):
                    result.append({
                        'id': row[1],
                        'name': row[2],
                        'sticker': row[3],
                    })
                conn.close()
                return result

            def send_list_of_stickers(text):
                def handler(msg):
                    content_type, chat_type, chat_id = telepot.glance(msg)

                    list_of_stickers = get_list_of_stickers_from_db(chat_id)

                    # Send a list of stickers from db
                    msgsent = self.sender.sendMessage(
                        'You have {:d} stickers.'.format(len(list_of_stickers))
                    )
                    for i, item in enumerate(list_of_stickers):
                        msgsent = self.sender.sendMessage(
                            '{:d}: {:s}'.format(i + 1, item['name'])
                        )
                        bot.sendSticker(chat_id, item['sticker'])
                    return msgsent
                return handler

            def add_sticker_handler_1(text):
                def handler(msg):
                    msgsent = self.sender.sendMessage(text)
                    return msgsent
                return handler

            def add_sticker_tester_2(text):
                def tester(msg):
                    if self._count == 1 and content_type == 'sticker':
                        return True
                    else:
                        return False
                return tester

            def add_sticker_handler_2(text):
                def handler(msg):
                    msgsent = self.sender.sendMessage('Write a description.')
                    self.temp_sticker = msg['sticker']['file_id']
                    self._count = 2
                    return msgsent
                return handler

            def add_sticker_tester_3(text):
                def tester(msg):
                    if self._count == 2 and content_type == 'text':
                        return True
                    else:
                        return False
                return tester

            def add_sticker_handler_3(text):
                def handler(msg):
                    conn, c = connect_to_db(config.db_filename)

                    max_sticker_id = 0
                    for row in c.execute("SELECT * from stickers WHERE user=?",
                                         (chat_id,)):
                        max_sticker_id = max(int(row[1]), max_sticker_id)
                    c.execute(
                        "INSERT INTO stickers VALUES (?,?,?,?)",
                        (msg['from']['id'],
                         max_sticker_id + 1,
                         msg['text'],
                         self.temp_sticker,)
                    )
                    conn.commit()
                    conn.close()
                    msgsent = self.sender.sendMessage(
                        'Done. Now you can use @{:s} to find the sticker.'
                        .format(config.botname)
                    )
                    self._count = 0
                    return msgsent
                return handler

            def contains_word(word):
                def tester(msg):
                    content_type, chat_type, chat_id = telepot.glance(msg)
                    if content_type == 'text':
                        if (re.compile(r'{:s}'.format(word), re.IGNORECASE)
                                    .search(msg['text'])):
                            return True
                    return False
                return tester

            def remove_sticker(text):
                def handler(msg):
                    content_type, chat_type, chat_id = telepot.glance(msg)
                    removeRegex = re.compile(r'/remove (\d+)')
                    regex_result = removeRegex.search(msg['text'])

                    if regex_result:
                        sticker_number_from_user = int(regex_result[1])

                        list_of_stickers = get_list_of_stickers_from_db(chat_id)

                        for i, item in enumerate(list_of_stickers):  # [:10]
                            if i + 1 == sticker_number_from_user:
                                conn, c = connect_to_db(config.db_filename)
                                c.execute(
                                    "DELETE FROM stickers WHERE user = ? AND id = ?",
                                    (msg['from']['id'],
                                     item['id'],))
                                conn.commit()
                                conn.close()
                                msgsent = self.sender.sendMessage(
                                          'Sticker removed.')
                                break
                        else:
                            msgsent = self.sender.sendMessage('Sticker not found.')
                    return msgsent
                return handler

            handlers = [
                [text_match(r'/list'), send_list_of_stickers(None)],
                [text_match(r'/add'), add_sticker_handler_1('Send a sticker.')],
                [contains_word(r'/remove'), remove_sticker(None)],
                [add_sticker_tester_2(None), add_sticker_handler_2(None)],
                [add_sticker_tester_3(None), add_sticker_handler_3(None)],
            ]

            for tester, handler in handlers:
                if tester(msg):
                    handler(msg)
                    break


if __name__ == '__main__':
    if not os.path.exists(config.db_filename):
        conn, c = connect_to_db(config.db_filename)
        c.execute('''CREATE TABLE stickers
                     (user integer, id integer, name text, sticker text)''')
        conn.commit()
        conn.close()

    bot = telepot.DelegatorBot(config.TOKEN, [
        # Inline query handler
        pave_event_space()(
            per_inline_from_id(), create_open, QueryCounter, timeout=10),
        # Private messages handler
        pave_event_space()(
            per_chat_id(), create_open, MessageCounter, timeout=300)])
    MessageLoop(bot).run_as_thread()
    print('I am {:s}, nice to meet you'.format(config.botname))

    while 1:
        time.sleep(10)
