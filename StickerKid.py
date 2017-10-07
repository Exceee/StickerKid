#! /usr/bin/env python3.6

import logging
import os
import re
import sqlite3
import time

from fuzzywuzzy import fuzz
import telepot
from telepot.loop import MessageLoop
from telepot.delegate import pave_event_space, per_inline_from_id, per_chat_id, create_open
from telepot.namedtuple import InlineQueryResultCachedSticker, InlineQueryResultArticle, InputTextMessageContent

import configmy

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)


# Inline query handlers

def find_sticker_in_db(user_id, sticker):
    # Connect to db
    conn = sqlite3.connect('StickerKid.db')
    c = conn.cursor()

    # Create the result - list of dicts with matched stickers
    result = list()
    for row in c.execute("SELECT * from stickers WHERE user=?", (user_id,)):
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


class QueryCounter(telepot.helper.InlineUserHandler, telepot.helper.AnswererMixin):
    def __init__(self, *args, **kwargs):
        super(QueryCounter, self).__init__(*args, **kwargs)
        self._count = 0

    def on_inline_query(self, msg):
        def compute():
            query_id, from_id, query_string = telepot.glance(msg, flavor='inline_query')
            helpful_log = self.id, ':', 'Inline Query:', query_id, from_id, query_string
            logger.info(helpful_log)

            self._count += 1
            search_result = find_sticker_in_db(from_id, query_string)
            if search_result:
                articles = list()
                for item in search_result:
                    articles.append(InlineQueryResultCachedSticker(
                                 id=str(item['id']),
                                 sticker_file_id=item['sticker'],
                            ))
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

    def on_chosen_inline_result(self, msg):
        result_id, from_id, query_string = telepot.glance(msg, flavor='chosen_inline_result')
        logger.info(self.id, ':', 'Chosen Inline Result:', result_id, from_id, query_string)


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

            def send_list_of_stickers(text):
                def handler(msg):
                    content_type, chat_type, chat_id = telepot.glance(msg)

                    conn = sqlite3.connect('StickerKid.db')
                    c = conn.cursor()

                    result = list()
                    for row in c.execute(
                            "SELECT * from stickers WHERE user=? ORDER BY id",
                            (chat_id,)):
                        result.append({'id': row[1],
                                       'name': row[2],
                                       'sticker': row[3]})

                    conn.close()

                    # Send a list of stickers from db
                    msgsent = self.sender.sendMessage('You have {:d} stickers.'
                                              .format(len(result)))
                    for i, item in enumerate(result):
                        msgsent = self.sender.sendMessage('{:d}: {:s}'.format(i + 1, item['name']))
                        bot.sendSticker(chat_id, item['sticker'])
                    return msgsent
                return handler

            def send_text_add_sticker(text):
                def handler(msg):
                    msgsent = self.sender.sendMessage(text)
                    self._count = 1
                    return msgsent
                return handler

            def contains_word_on_the_beginning(text):
                def tester(msg):
                    content_type, chat_type, chat_id = telepot.glance(msg)
                    if content_type == 'text':
                        for word in text:
                            if (re.compile(r'\b{:s}'.format(word), re.IGNORECASE)
                                           .search(msg['text'])):
                                return True
                    return False
                return tester

            def remove_sticker(text):
                def handler(msg):
                    content_type, chat_type, chat_id = telepot.glance(msg)

                    removeRegex = re.compile(
                        r'/remove (\d)*')
                    regex_result = removeRegex.search(msg['text'])

                    if regex_result:
                        sticker_id = int(regex_result[1])
                        conn = sqlite3.connect('StickerKid.db')
                        c = conn.cursor()

                        result = list()
                        for row in c.execute("SELECT * from stickers WHERE user=? ORDER BY id",
                                (chat_id,)):
                            result.append({'id': row[1],
                                           'name': row[2],
                                           'sticker': row[3]})

                        c.execute("SELECT count(*) FROM stickers WHERE user = ? AND id = ?",
                                  (msg['from']['id'],
                                   sticker_id,))
                        data = c.fetchone()[0]
                        if not data == 0:
                            c.execute("DELETE FROM stickers WHERE id=?", (result[sticker_id - 1]['id'],))
                            conn.commit()
                            msgsent = self.sender.sendMessage('Sticker removed.')
                        else:
                            msgsent = self.sender.sendMessage('Sticker not found.')
                        conn.close()
                    return msgsent
                return handler

            handlers = [
                [text_match('/list'), send_list_of_stickers('')],
                [text_match('/add'), send_text_add_sticker('Send a sticker.')],
                [contains_word_on_the_beginning('/remove'), remove_sticker('')],
            ]

            for tester, handler in handlers:
                if tester(msg):
                    self._count = 0
                    msgsent = handler(msg)
                    break

            if self._count == 1 and content_type == 'sticker':

                self.sender.sendMessage('Write a description.')
                self.temp_sticker = msg['sticker']['file_id']
                self._count = 2

            elif self._count == 2 and content_type == 'text':

                conn = sqlite3.connect('StickerKid.db')
                c = conn.cursor()
                max_sticker_id = 0
                for row in c.execute("SELECT * from stickers WHERE user=?",
                                     (chat_id,)):
                    max_sticker_id = max(int(row[1]), max_sticker_id)
                c.execute(
                    "INSERT INTO stickers VALUES (?,?,?,?)",
                    (msg['from']['id'],
                     max_sticker_id + 1,
                     msg['text'],
                     self.temp_sticker,))
                conn.commit()
                conn.close()
                self.sender.sendMessage('Done. Now you can use @{:s} to find the sticker.'.format(configmy.botname))
                self._count = 0


if __name__ == '__main__':
    if not os.path.exists('StickerKid.db'):
        conn = sqlite3.connect('StickerKid.db')
        c = conn.cursor()
        c.execute('''CREATE TABLE stickers
                     (user integer, id integer, name text, sticker text)''')
        conn.commit()
        conn.close()

    bot = telepot.DelegatorBot(configmy.TOKEN, [
        # Inline query handler
        pave_event_space()(
            per_inline_from_id(), create_open, QueryCounter, timeout=10),
        # Private messages handler
        pave_event_space()(
                per_chat_id(), create_open, MessageCounter, timeout=300)])
    MessageLoop(bot).run_as_thread()
    print('I am {:s}, nice to meet you'.format(configmy.botname))

    while 1:
        time.sleep(10)
