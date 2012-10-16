#!/usr/bin/python

# This code was derived by code posted by Michiel Overtoom (http://www.michielovertoom.com/python/pastebin-abused/)
# Copyright (c) 2012, Bryan Brannigan
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
This code is intended to retrieve a list of pastes from pastebin once per minute.  Each paste is then individual downloaded and searched for strings which are defined in the searchstrings.txt file.  

Dependancies: BeautifulSoup,pymongo

This code might cause the world to implode.  Run at your own risk.  
"""

import sys, os, time, datetime, random, smtplib, re
import BeautifulSoup, threading, Queue, pymongo

from email import encoders
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from urllib2 import Request, urlopen, URLError, HTTPError
from httplib import BadStatusLine
from pymongo import Connection
from ConfigParser import SafeConfigParser

config = SafeConfigParser()
config.read('config.ini')

connection = Connection(config.get('mongodb', 'host'), int(config.get('mongodb', 'port')))
connection.datastore.authenticate(str(config.get('mongodb', 'user')), str(config.get('mongodb', 'password')))

paste_collection = connection.datastore.pastes
url_collection = connection.datastore.urls


pastes = Queue.Queue()

log = open("log.txt", "a")

searchstrings = []

def get_url_content(url):

    req_headers = {
        'User-Agent': 'Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:15.0) Gecko/20100101 Firefox/15.0.1',
        'Referer': 'http://pastebin.com'
    }

    try:
        content = urlopen(url).read()
    except HTTPError, e:
        log.write("Bombed out on %s... HTTP Error (%s)... Letting it go...\n" % (url, e.code))
        return 0
    except URLError, e:
        log.write("Bombed out on %s... URL Error (%s)... Letting it go...\n" % (url, e.reason))
        return 0
    except BadStatusLine, e:
        log.write("Bombed out on %s... Bad Status Line (%s) ... Letting it go...\n" % (url, e.reason))
        return 0

    return content

def safe_unicode(obj, *args):
    """ return the unicode representation of obj """
    try:
        return unicode(obj, *args)
    except UnicodeDecodeError:
        # obj is byte string
        ascii_text = str(obj).encode('string_escape')
        return unicode(ascii_text)

def downloader():

    while pastes.qsize() > 0:
        paste = pastes.get()

        dupe_check = {"pastesource": "Pastebin", "pasteid": paste}
        if paste_collection.find_one(dupe_check) is not None:
            pastes.task_done()
            continue

        content = get_url_content("http://pastebin.com/raw.php?i=" + paste)

        if content == 0:
            #pastes.put(paste)
            pastes.task_done()
            continue

        if "requesting a little bit too much" in content:
            log.write("Throttling... requeuing %s... (%d left)\n" % (paste, pastes.qsize()))
            pastes.put(paste)
	    time.sleep(0.1)
        else:
            log.write("Downloaded %s... (%d left)\n" % (paste, pastes.qsize())) 

            try:
                matches = re.findall("(?P<url>https?://[^\s]+)",  content.lower())
                for match in matches:
                    url_info = {"pastesource": "Pastebin", "pasteid": paste, "url": safe_unicode(match)}
                    url_collection.insert(url_info)
            except:
                time.sleep(.1)

            string_found = 0
            for s in searchstrings:
	         if re.search(s.strip(), content, flags=re.IGNORECASE|re.MULTILINE|re.DOTALL): 
                    log.write(s.strip() + " found in %s\n" % paste) 
                    emailalert(content,s.strip(),paste)
                    string_found = 1

            paste_info = {"pastesource": "Pastebin", "pasteid": paste, "insertdate": datetime.datetime.utcnow(), "content": safe_unicode(content), "string_found": string_found}
            insid = paste_collection.insert(paste_info)

            log.write("%s Inserted... (%s)\n" % (paste, insid)) 

        log.flush()
        time.sleep(random.uniform(1, 3))
        pastes.task_done()

def scraper():
    failures = 0
    while True:

        content = get_url_content("http://www.pastebin.com/archives/")

        if not (content):
            time.sleep(10)
            failures += 1

            #Three failures in a row? Go into a holding pattern.
            if failures > 2:
                log.write("3 Failures in a row. Holding Pattern")
                time.sleep(450)
                failures = 0

            continue

        failures = 0

        links = 0
	inserts = 0 
	dupes = 0

        soup = BeautifulSoup.BeautifulSoup(content)
        for link in soup.html.table.findAll('a'):
           href = link.get('href')
           if '/' in href[0] and len(href) == 9:
              links += 1
              href = href[1:] # chop off leading /
              pastes.put(href)
              inserts += 1

        log.write("%d links found. %d queued, %d duplicates\n" % (links, inserts, dupes))

	log.flush() 
        time.sleep(60)

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

log.write("Starting the Scraper\n")

scraper_thread = threading.Thread(target=scraper)
scraper_thread.daemon = True
scraper_thread.start()

log.write("Pastebin Parser is GO\n")

while True:

    if not scraper_thread.isAlive():
        scraper_thread.start()

    searchstrings = open("searchstrings.txt").readlines()

    suggested_threads = int(pastes.qsize() / 100)
    actual_threads = int(config.get('threads', 'min_count'))

    if (suggested_threads > actual_threads):
         if (actual_threads < int(config.get('threads', 'max_count'))): 
             actual_threads = suggested_threads
         else:
             actual_threads = int(config.get('threads', 'max_count'))


    if pastes.qsize() > 0 and (threading.active_count() < (actual_threads + 1)):
        while (threading.active_count() < (actual_threads + 1)):
            log.write("Spinning Up Downloader Thread... (%d in the queue)\n" % pastes.qsize())
            t = threading.Thread(target=downloader)
            t.setDaemon(True)
            t.start()
            if (pastes.qsize() == 0):
                log.write("The queue is empty. Let us dine with the philosophers\n")
                break

    log.write("Threads: Min %d - Suggested %d - Max %d - Actual %d - Scraper Alive: %s\n" % (int(config.get('threads', 'min_count')), suggested_threads, int(config.get('threads', 'max_count')), threading.active_count() - 1, str(scraper_thread.isAlive())))
    log.flush()
    time.sleep(10)

