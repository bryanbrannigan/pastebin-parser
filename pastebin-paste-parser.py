#!/usr/bin/python

# This code was derived by code posted by Michiel Overtoom (http://www.michielovertoom.com/python/pastebin-abused/)
# Copyright (c) 2012, Bryan Brannigan, Ben Jackson
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:
#
#     * Redistributions of source code must retain the above copyright notice,
#       this list of conditions and the following disclaimer.
#     * Redistributions in binary form must reproduce the above copyright
#       notice,this list of conditions and the following disclaimer in the
#       documentation and/or other materials provided with the distribution.
#     * Neither the name of the copyright holder nor the names of its
#       contributors may be used to endorse or promote products derived from
#       this software without specific prior written permission.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
# AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
# IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
# ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT OWNER OR CONTRIBUTORS BE
# LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR
# CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF
# SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS
# INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN
# CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE)
# ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
# POSSIBILITY OF SUCH DAMAGE.

"""
This code is intended to retrieve paste contents from a remote queue.  Each paste is processed for strings and inserted in to MongoDB.

Dependancies: pika,pymongo

This code might cause the world to implode.  Run at your own risk.  
"""

import sys, os, time, datetime, random, smtplib, re, pika, pymongo

from email import encoders
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pymongo import Connection
from ConfigParser import SafeConfigParser

connection = Connection()
paste_collection = connection.datastore.pastes
url_collection = connection.datastore.urls

config = SafeConfigParser()
config.read('config.ini')

log = open("parser-log.txt", "a")

searchstrings = []
searchstringsfile = open("searchstrings.txt")
searchstrings = searchstringsfile.readlines()

mq = pika.BlockingConnection(pika.ConnectionParameters('localhost'))
channel = mq.channel()
channel.queue_declare(queue='pastes_data', durable=True)

def safe_unicode(obj, *args):
    """ return the unicode representation of obj """
    try:
        return unicode(obj, *args)
    except UnicodeDecodeError:
        # obj is byte string
        ascii_text = str(obj).encode('string_escape')
        return unicode(ascii_text)

def parser(ch, method, properties, content):
	log.write("Parsing %s...\n" % (properties.correlation_id))
        paste_info = {"pastesource": "Pastebin", "pasteid": properties.correlation_id, "insertdate": datetime.datetime.utcnow(), "content": safe_unicode(content)}
        insid = paste_collection.insert(paste_info)
        log.write("%s Inserted... (%s)\n" % (properties.correlation_id, insid))
	try:
                matches = re.findall("(?P<url>https?://[^\s]+)",  content.lower())
                for match in matches:
                    url_info = {"pastesource": "Pastebin", "pasteid": properties.correlation_id, "url": safe_unicode(match)}
                    url_collection.insert(url_info)
        except:
                time.sleep(.1)

        for s in searchstrings:
                 if re.search(s.strip(), content, flags=re.IGNORECASE|re.MULTILINE|re.DOTALL):
                 #if s.strip().lower() in content.lower():
                    log.write(s.strip() + " found in %s\n" % properties.correlation_id)
                    emailalert(content,s.strip(),properties.correlation_id)

	log.flush()
	ch.basic_ack(delivery_tag = method.delivery_tag)	

def emailalert(content,keyword,paste):
    outer = MIMEMultipart()
    outer['Subject'] = 'Pastebin Parser Alert - Keyword: %s - Paste: %s' % (keyword, paste)
    outer['To'] = config.get('mail', 'receivers')
    outer['From'] = config.get('mail', 'sender')

    msg = MIMEText(content, 'plain')
    msg.add_header('Content-Disposition', 'attachment', filename='content.txt')
    outer.attach(msg)
    composed = outer.as_string()
    s = smtplib.SMTP(config.get('mail', 'smtpserver'))
    s.sendmail(config.get('mail', 'sender'),config.get('mail', 'receivers').split(','),composed)
    s.quit()

while True:
	log.write("Spinning Up Parser Thread...\n")
	channel.basic_consume(parser,queue='pastes_data',no_ack=False)
	channel.start_consuming()

