#!/usr/bin/env python2
# -*- coding: utf-8 -*-
# vim: set expandtab tabstop=4 shiftwidth=4 :

# paywall_breaker.py - A construct that, when given orders to do so, downloads
#   a web page while pretending to be a search engine's indexing spider, parses
#   the HTML to extract the salient stuff (i.e., the body of the page), and
#   archives it to a local Etherpad-Lite instance to read later.
#
#   This is part of the Exocortex Halo project
#   (https://github.com/virtadpt/exocortex-halo/).

# By: The Doctor <drwho at virtadpt dot net>
#       0x807B17C1 / 7960 1CDC 85C9 0B63 8D9F  DD89 3BD8 FF2B 807B 17C1

# License: GPLv3

# v1.3 - Added an explicit version for the Etherpad-Lite API because the last
#        major release included some security fixes that bumped the version
#        number.  It breaks otherwise.
# v1.2 - Added some HTTP request code handlers.
#      - Added an exception handler.
# v1.1 - Figured out how to strip out all CSS and JS to make pages easier to
#        deal with in the pad.
#      - Got tired of fighting with the padID argument in Etherpad-Lite's API
#        and went back to using a SHA-1 hash of the page to uniquely identify
#        in the database.  Coupled with the search function of Etherpad-Lite
#        everything is now much more smooth.
# v1.0 - Initial release.

# TO-DO:
# - Figure out how to grab and archive regular text and not HTML (for example,
#   Pastebin /raw URLs).

# Load modules.
from bs4 import BeautifulSoup
from email.mime.text import MIMEText
from etherpad_lite import EtherpadLiteClient, EtherpadException

import argparse
import ConfigParser
import hashlib
import json
import logging
import os
import random
import requests
import smtplib
import sys
import time
import validators

# Constants.

# Global variables.
# Handle to an argument parser object.
argparser = None

# Handle to the parsed arguments.
args = None

# Path to a configuration file.
config_file = ""

# Handle to a configuration file parser.
config = None

# URL of the message queue to pull orders from.
message_queue = ""

# The "http://system:port/" part of the message digest URL.
server = ""

# Name of the construct.
bot_name = ""

# Default e-mail to send messages to.
default_email = ""

# Loglevel to emit messages at.
config_log = ""

# Number of seconds in between pings to the message queue.
polling_time = 0

# Hostname of the SMTP server to use to send messages to the bot's user.
smtp_server = "localhost"

# Originating e-mail address the construct will use to identify itself.
origin_email_address = ""

# URL and API key of the Etherpad-Lite instance to use as an archive.
etherpad_url = ""
etherpad_api_key = ""

# Version of the Etherpad-Lite API to use.
api_version = "1"

# URL that the user will access pad pages through.
archive_url = ""

# Handle to the configuration file section containing user agent strings.
user_agent_strings = None

# Name of the search engine whose user-agent string is in the config file.
search_engine = ""

# List of search engine user agents to spoof when making requests.
user_agents = []

# Important parts of the web page that we want to extract and save.
title = ""
body = ""

# String which holds the subject line of the message to the user when a job
# is done.
subject_line = ""

# String which holds the message to the user when the job is done.
message = ""

# Handle to a requests object.
request = None

# URL of the page to grab.
page_request = ""

# Handle to an Etherpad-Lite page.
etherpad = None

# String that holds the contents of the web page to send to Etherpad-Lite.
page_text = ""

# padID for Etherpad-Lite.
pad_id = ""

# Handle to a SHA-1 hasher.
hash = None

# Functions.
# set_loglevel(): Turn a string into a numerical value which Python's logging
#   module can use because.
def set_loglevel(loglevel):
    if loglevel == "critical":
        return 50
    if loglevel == "error":
        return 40
    if loglevel == "warning":
        return 30
    if loglevel == "info":
        return 20
    if loglevel == "debug":
        return 10
    if loglevel == "notset":
        return 0

# parse_get_request(): Takes a string and susses out the URL the user wants
#   grabbed and archived.  Commands are of the form "Botname, get
#   https://www.example.com/paywalled_page.html".  Returns the URL to download
#   and parse or an error message.
def parse_get_request(get_request):
    logger.debug("Entered function parse_get_request().")
    words = []

    # Clean up the get request.
    get_request = get_request.strip()
    get_request = get_request.strip('.')

    # If the get request is empty (i.e., nothing in the queue), bounce.
    if "no commands" in get_request:
        logger.debug("Got empty get request.")
        return

    # Tokenize the get request.
    words = get_request.split(' ')
    logger.debug("Tokenized get request: " + str(words))

    # User asked for help.
    if words[0].lower() == "help":
        logger.debug("User asked for online help.")
        return words[0]

    # "get <URL>"
    if words[0].lower() == "get":
        # Ditch the 'get' request.
        del words[0]

        # Make sure the command isn't truncated.
        if not len(words):
            return "ERROR: There was no URL there."

        # Try to validate that whatever's left in the list is an URL.
        if not validators.url(words[0]):
            return "ERROR: '" + str(words) + "' was not a valid URL."
        else:
            return words[0]

# email_response(): Function that e-mails something to the bot's user.  Takes
#   two arguments, strings containing a subject line and a message.  Uses the
#   configured SMTP server to send the message.  Returns True (it worked) or
#   False (it didn't go through).
def email_response(subject_line, message):
    smtp = None

    # Due diligence.
    if not subject_line:
        return False
    if not message:
        return False

    # Set up the outbound message.
    message = MIMEText(message)
    message['Subject'] = subject_line
    message['From'] = origin_email_address
    message['To'] = default_email
    logger.debug("Created outbound e-mail.")

    # Set up the SMTP connection and transmit the message.
    logger.info("E-mail message to " + default_email)
    smtp = smtplib.SMTP(smtp_server)
    smtp.sendmail(origin_email_address, default_email, message.as_string())
    smtp.quit()
    logger.info("Message transmitted.  Deallocating SMTP server object.")
    smtp = None
    return True

# download_web_page(): This function takes a URL from the bot's user and
#   downloads it while spoofing the User-Agent field of the request in an
#   attempt to evade paywalls.  It returns two essential pieces of the web
#   page, the parsed contents of the <title>, and <body> segments of the page.
#   In the event of problems it returns None, and None for all two values.
def download_web_page(url):

    # Essential values.
    title = ""
    body = ""

    # Custom headers for the HTTP request.
    custom_headers = {}

    # Handle to a requests object (how's that for an awkward module name?).
    request = None

    # Handle to a BeautifulSoup parser object.
    parsed_html = None

    # Pick a random user agent.
    user_agent = user_agents[random.randrange(0, stop=len(user_agents))]
    logger.debug("Spoofing user agent '" + user_agent + "'.")
    custom_headers['user-agent'] = user_agent

    # Make the HTTP request.
    logger.debug("Making HTTP request to " + url)
    request = requests.get(url, headers=custom_headers)

    # Check to see if the request worked.
    if not request:
        logger.warn("Request object errored out and was unable to do anything.  Uh-oh.")
        return (None, None)

    # Some web server that get into a bad state throw invalid HTTP error
    # codes (such as "'" (yes, a single quote) or an empty string).  Trap such
    # situations.
    if type(request.status_code) != int:
        logger.warn("Got something that isn't an HTTP status code.  WTF?")
        return (None, None)
    if not request.status_code:
        logger.warn("Got an empty HTTP status code.  WTF?")
        return (None, None)

    if request.status_code >= 500:
        logger.warn("Got HTTP status code " + str(request.status_code) + ".  Something went wrong on the destination web server.")
        return (None, None)

    if request.status_code >= 400:
        logger.warn("Got HTTP status code " + str(request.status_code) + ".  Something went wrong with the request I made.")
        return (None, None)

    if request.status_code != 200:
        logger.warn("Got HTTP status code " + str(request.status_code) + ".  Uh-oh.")
        return (None, None)

    # Parse the returned HTML.
    logger.debug("Got URL " + url + ".  Now to parse it.")
    parsed_html = BeautifulSoup(request.text, 'html.parser')

    # Silently rip out the CSS and JavaScript because, technically, those are
    # part of the text.
    for i in parsed_html(["script", "style"]):
        foo = i.extract()

    # Extract the bits we want.  We need to explicitly change everything to
    # UTF-8 so the rest of our code won't barf.
    try:
        title = parsed_html.head.text.encode('utf-8')
    except:
        title = "No <head></head> tagset found."

    try:
        body = parsed_html.get_text().encode('utf-8')
    except:
        body = "Unable to pull any text out of the HTML page.  What the hell?"

    # We're done here.
    return (title, body)

# send_message_to_user(): Function that does the work of sending messages back
# to the user by way of the XMPP bridge.  Takes one argument, the message to
#   send to the user.  Returns a True or False which delineates whether or not
#   it worked.
def send_message_to_user(message):
    logger.debug("Entered function send_message_to_user().")

    # Headers the XMPP bridge looks for for the message to be valid.
    headers = {'Content-type': 'application/json'}

    # Set up a hash table of stuff that is used to build the HTTP request to
    # the XMPP bridge.
    reply = {}
    reply['name'] = bot_name
    reply['reply'] = message

    # Send an HTTP request to the XMPP bridge containing the message for the
    # user.
    request = requests.put(server + "replies", headers=headers,
        data=json.dumps(reply))

# Core code...
# Set up the command line argument parser.
argparser = argparse.ArgumentParser(description='A construct that polls a message queue for the URLs of paywalled web pages, tries to download the pages, copies them into an archive, and sends the results to a destination.')

# Set the default config file and the option to set a new one.
argparser.add_argument('--config', action='store', 
    default='./paywall_breaker.conf')

# Loglevels: critical, error, warning, info, debug, notset.
argparser.add_argument('--loglevel', action='store',
    help='Valid log levels: critical, error, warning, info, debug, notset.  Defaults to INFO.')

# Time (in seconds) between polling the message queues.
argparser.add_argument('--polling', action='store', default=60,
    help='Default: 60 seconds')

# Parse the command line arguments.
args = argparser.parse_args()
if args.config:
    config_file = args.config

# Read the options in the configuration file before processing overrides on the
# command line.
config = ConfigParser.ConfigParser()
if not os.path.exists(config_file):
    logging.error("Unable to find or open configuration file " +
        config_file + ".")
    sys.exit(1)
config.read(config_file)

# Get the URL of the message queue to contact.
server = config.get("DEFAULT", "queue")

# Get the name of the message queue to report to.
bot_name = config.get("DEFAULT", "bot_name")

# Construct the full message queue name.
message_queue = server + bot_name

# Get the default e-mail address.
default_email = config.get("DEFAULT", "default_email")

# Get the default loglevel of the bot.
config_log = config.get("DEFAULT", "loglevel").lower()
if config_log:
    loglevel = set_loglevel(config_log)

# Set the number of seconds to wait in between polling runs on the message
# queues.
try:
    polling_time = config.get("DEFAULT", "polling_time")
except:
    # Nothing to do here, it's an optional configuration setting.
    pass

# Get the SMTP server to send search results through from the config file if
# it's been set.
try:
    smtp_server = config.get("DEFAULT", "smtp_server")
except:
    # Nothing to do here, it's an optional configuration setting.
    pass

# Get the e-mail address that search results will be sent from.
origin_email_address = config.get("DEFAULT", "origin_email_address")

# Set the loglevel from the override on the command line.
if args.loglevel:
    loglevel = set_loglevel(args.loglevel.lower())

# Configure the logger.
logging.basicConfig(level=loglevel, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

# Set the message queue polling time from override on the command line.
if args.polling:
    polling_time = args.polling

# Get the URL of the Etherpad-Lite instance to contact.
etherpad_url = config.get("DEFAULT", "etherpad_url")

# Get the API key of the Etherpad-Lite instance.
etherpad_api_key = config.get("DEFAULT", "etherpad_api_key")

# Get the version of the REST API the Etherpad-Lite server supports.
api_version = config.get("DEFAULT", "api_version")

# Get the URL that the user will access pad pages through.
archive_url = config.get("DEFAULT", "archive_url")

# Get the list of user agents from the configuration file and load them into
# a list.
user_agent_strings = config.items("user agents")
for search_engine, user_agent in user_agent_strings:
    if "engine" in search_engine:
        user_agents.append(user_agent)

# Debugging output, if required.
logger.info("Everything is configured.")
logger.debug("Values of configuration variables as of right now:")
logger.debug("Configuration file: " + config_file)
logger.debug("Server to report to: " + server)
logger.debug("Message queue to report to: " + message_queue)
logger.debug("Bot name to respond to search requests with: " + bot_name)
logger.debug("Default e-mail address to send results to: " + default_email)
logger.debug("Time in seconds for polling the message queue: " +
    str(polling_time))
logger.debug("SMTP server to send search results through: " + smtp_server)
logger.debug("E-mail address that search results are sent from: " +
    origin_email_address)
logger.debug("URL of the Etherpad-Lite instance: " + etherpad_url)
logger.debug("API key for the Etherpad-Lite instance: " + etherpad_api_key)
logger.debug("Version of the REST API the Etherpad-Lite instance supports: " + str(api_version))
logger.debug("URL of the Etherpad-Lite archive: " + archive_url)
logging.debug("User agents that will be spoofed: " + str(user_agents))

# Go into a loop in which the bot polls the configured message queue to see
# if it has any HTTP requests waiting for it.
logger.debug("Entering main loop to handle requests.")
send_message_to_user(bot_name + " now online.")
while True:

    # Reset variables that control the archived page and outbound e-mail.
    title = ""
    body = ""
    subject_line = ""
    message = ""
    page_text = ""
    pad_id = ""
    hash = hashlib.sha1()

    # Check the message queue for search requests.
    try:
        logger.debug("Contacting message queue: " + message_queue)
        request = requests.get(message_queue)
        logger.debug("Response from server: " + request.text)
    except:
        logger.warn("Connection attempt to message queue timed out or failed.  Going back to sleep to try again later.")
        time.sleep(float(polling_time))
        continue

    # Test the HTTP response code.
    # Success.
    if request.status_code == 200:
        logger.debug("Message queue " + bot_name + " found.")

        # Extract the search request.
        page_request = json.loads(request.text)
        logger.debug("Command from user: " + str(page_request))
        page_request = page_request['command']

        # Parse the page request.
        page_request = parse_get_request(page_request)
        if page_request:
            logger.debug("Parsed page get request: " + page_request.encode("utf-8"))

        # If there was no page request, go back to sleep.
        if not page_request:
            time.sleep(float(polling_time))
            continue

        # Test to see if a valid page request was received.  If not, send a
        # failure message back to the user.
        if "ERROR: " in page_request:
            logger.debug("An invalid URL was received by the construct.")
            send_message_to_user("That was an invalid URL.  Try again.")
            time.sleep(float(polling_time))
            continue

        # If the user is requesting help, assemble a response and send it back
        # to the server's message queue.
        if page_request.lower() == "help":
            reply = "My name is " + bot_name + " and I am an instance of " + sys.argv[0] + ".\n"
            reply = reply + """I am capable of jumping most paywalls by spoofing the User-Agent header of a randomly selected search engine, downloading the content, rendering it as plain text, and copying it into a new Etherpad-Lite page for editing and archival.  I will then e-mail you a link to the new page.  I will both e-mail and send you the link to the archived page directly.  To archive a page, send me a message that looks something like this:\n\n"""
            reply = reply + bot_name + ", get https://www.example.com/foo.html"
            send_message_to_user(reply)
            continue

        # Try to download the HTML page the user is asking for.
        send_message_to_user("Downloading the web page...")
        (title, body) = download_web_page(page_request)

        # Did it work?
        if not title or not body:
            reply = "I was unable to get anything useful from the page at URL " + page_request + ".  Either the HTML's completely broken, it's not HTML at all, or the URL's bad."
            send_message_to_user(reply)
            time.sleep(float(polling_time))
            continue

        # Clean up the title for later.
        title = title.strip()

        # Take a SHA-1 hash of the article because that seems to be the most
        # reliable way of generating a valid padID for Etherpad-Lite.
        hash.update(title)
        hash.update(body)
        pad_id = hash.hexdigest()

        # Contact Etherpad and create a new pad with the contents of the page.
        etherpad = EtherpadLiteClient(base_params={'apikey': etherpad_api_key},
            api_version=api_version)
        page_text = str(title) + "\n\n" + str(body) + "\n"
        try:
            etherpad.createPad(padID=pad_id, text=page_text)
        except EtherpadException as e:
            logger.warn("Etherpad-Lite module threw an exception: " + str(e))
            send_message_to_user(str(e))
            time.sleep(float(polling_time))
            continue

        # E-mail a success message with a link to the archived page to the
        # bot's user.
        subject_line = "Successfully downloaded page '" + title + "'"
        message = "I have successfully downloaded and parsed the text of the web page '" + title + "'.  You can read the page at the URL " + archive_url + pad_id 
        if not email_response(subject_line, message):
            logger.warn("Unable to e-mail failure notice to the user.")

        send_message_to_user(message)

        # Go back to sleep and wait for the next command.
        logger.info("Done.  Going back to sleep until the next episode.")
        time.sleep(float(polling_time))
        continue

# Fin.
sys.exit(0)

