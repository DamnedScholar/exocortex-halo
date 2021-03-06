#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# vim: set expandtab tabstop=4 shiftwidth=4 :

# web_index_bot.py - Bot written in Python that, when given a URL via its
#   message queue, submits it to as many search engines and/or online content
#   archives that are configured for this bot.
#
#   This is part of the Exocortex Halo project
#   (https://github.com/virtadpt/exocortex-halo/).

# By: The Doctor <drwho at virtadpt dot net>
#       0x807B17C1 / 7960 1CDC 85C9 0B63 8D9F  DD89 3BD8 FF2B 807B 17C1

# License: GPLv3

# v2.4 - Added the ability to run one or more scripts whenever the bot is
#        passed a URL.  The script is supposed to take the URL as an argument,
#        do something, and return 0 on success or non-zero on failure.
#      - Found a few instances of logger.foo() that should have been
#        logging.foo().  Cleaned up for consistency's sake.
# v2.3 - Changed things so that you'll only see site-by-site updates if the
#        bot is in debug mode.
#      - Fixed the last few logger.warn() to logger.warning() holdouts.
# v2.2 - Reworked the startup logic so that being unable to immediately
#        connect to either the message bus or the intended service is a
#        terminal state.  Instead, it loops and sleeps until it connects and
#        alerts the user appropriately.
#      - Moved the user-definable text upward in the online help, to match
#        the other bots.
# v2.1 - Added user-definable text to the help and about-to-do-stuff parts.
#      - Changed the default polling time to 10 seconds, because this bot
#        won't be run on a Commodore 64...
#      - Got rid of some redundancy.
#      - Fixed some comments.
#      - Cleaned up code formatting and conventions to match later generation
#        bots.  Also, it's a good excuse for rereading the code with a
#        critical eye.
#      - Broke the online help out into a function.
# v2.0 - Ported to Python 3.
# v1.2 - Made the overly chatty status reports contingent upon the bot running
#        in loglevel.DEBUG.
#      - Added the ability to URL encode URLs to index or archive because some
#        online archives require it (e.g., archive.fo).
# v1.1 - Added some code to send a notification of a successful submission back
#        to the user through the XMPP bridge.
#      - Added some code to warn of an unsuccessful submission of a URL.
# v1.0 - Initial release.

# TO-DO:
# - Make it possible to configure no search engines at all (and not pester the
#   user with messages about failed requests) so that the user can use this
#   bot to only run external utilities with passed URLs.

# Load modules.
import argparse
import configparser
import json
import logging
import os
import re
import requests
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

# Constants.
# When POSTing something to a service, the correct Content-Type value has to
# be set in the request.
custom_headers = {"Content-Type": "application/json"}

# Global variables.
# Handle to a logging object.
logger = ""

# Path to and name of the configuration file.
config_file = ""

# Loglevel for the bot.
loglevel = logging.INFO

# The "http://system:port/" part of the message queue URL.
server = ""

# URL to the message queue to take marching orders from.
message_queue = ""

# The name the search bot will respond to.  The idea is, this bot can be
# instantiated any number of times with different config files to use
# different search engines on different networks.
bot_name = ""

# How often to poll the message queues for orders.
polling_time = 10

# Global list of search engines' URLs to submit URLs to.
search_engines = []

# Handle to an index request from the user.
index_request = None

# Handle to the result of an index request from the user.
index_result = None

# Optional user-defined text strings for the online help and user interaction.
user_text = None
user_acknowledged = None

# A list of one or more external utilities the bot will run when the user sends
# it a URL.
external_scripts = []

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

# parse_index_request(): Takes a string and figures out if it was a correctly
#   formatted request to submit a URL to a bunch of search engines.  Requests
#   are of the form "index <some URL here>".  Returns the URL to submit for
#   indexing or None if it's not a well-formed request.
def parse_index_request(index_request):
    logging.debug("Entered function parse_index_request().")
    index_url = ""
    words = []

    # Clean up the search request.
    index_request = index_request.strip()
    index_request = index_request.strip(",")
    index_request = index_request.strip(".")
    index_request = index_request.strip("'")

    # If the search request is empty (i.e., nothing in the queue) return None.
    if "no commands" in index_request:
        logging.debug("Got an empty index request.")
        return None

    # Tokenize the search request.
    words = index_request.split()
    logging.debug("Tokenized index request: " + str(words))

    # Start parsing the the index request to see what kind it is.  After
    # making the determination, remove the words we've sussed out to make the
    # rest of the query easier.

    # User asked for help?
    if not len(words):
        return None
    if words[0].lower() == "help":
        logging.debug("User asked for online help.")
        return words[0]

    # User asked the construct to submit the URL for indexing?
    if (words[0] == "index") or (words[0] == "spider") or \
            (words[0] == "submit" or words[0] == "store" or \
            words[0] == "archive" or words[0] == "get"):
        logging.info("Got a token that suggests that this is an index request.")
    del words[0]

    # If the parsed search term is now empty, return an error.
    if not len(words):
        logging.error("The indexing request appears to be empty.")
        return None

    # Convert the remainder of the list into a URI-encoded string.
    index_url = words[0]
    logging.debug("Index URL: " + index_url)
    return index_url

# submit_for_indexing(): Function that takes as its argument a URL to submit
#   to one or more search engines.  It walks through search_engines[]
#   (declared in the global context) and submits the URL to each on in turn.
def submit_for_indexing(index_term):
    logging.debug("Entered function submit_for_indexing().")

    # URL encode the indexing request?
    urlencode = "no"

    # Method that should be used to send the URL to the search engine.
    method = ""

    # URL which represents the search engine to submit indexing requests to.
    url = ""

    # Handle to an HTTP(S) request.
    request = None

    # Generic flag that determines whether or not the process worked.
    result = False

    for url in search_engines:
        # Split the method and the submission URL.
        (urlencode, method, url) = url.split(',')
        logging.debug("Value of urlencode: " + urlencode)

        # Build the full submission URL.
        # If the urlencode flag is set, it means that the archive requires the
        # URLs sent to it to be URL encoded.
        if urlencode == "yes":
            url = url + urllib.parse.quote_plus(index_term)
            logging.debug("URL encoding requested: " + str(index_term))
        else:
            url = url + index_term
        try:
            if method == "get":
                request = requests.get(url)
            if method == "put":
                request = requests.put(url)
            if method == "post":
                request = requests.post(url)
            result = True

            # Only pester the user in debug mode.
            if loglevel == 10:
                send_message_to_user("Successfully submitted link " + url + ".")
        except:
            logging.warning("Unable to submit URL: " + str(url))
            send_message_to_user("ERROR: Unable to submit link " + url + ".")

        # Reset the urlencode flag to keep from breaking the other engines.
        urlencode = "no"

    # Return the overall results.
    return result

# send_message_to_user(): Function that does the work of sending messages back
# to the user by way of the XMPP bridge.  Takes one argument, the message to
#   send to the user.  Returns a True or False which delineates whether or not
#   it worked.
def send_message_to_user(message):
    # Set up a hash table of stuff that is used to build the HTTP request to
    # the XMPP bridge.
    reply = {}
    reply["name"] = bot_name
    reply["reply"] = message

    # Send an HTTP request to the XMPP bridge containing the message for the
    # user.
    request = requests.put(server + "replies", headers=custom_headers,
        data=json.dumps(reply))

# online_help(): Utility function that sends online help to the user when
#   requested.  Takes no args.  Returns nothing.
def online_help():
    reply = "My name is " + bot_name + " and I am an instance of " + sys.argv[0] + ".\n\n"
    if user_text:
        reply = reply + user_text + "\n\n"
    reply = reply + "I am capable of accepting URLs for arbitrary websites and submitting them for indexing by the search engines and online archives specified in my configuration file (some of which you may control, of course).  To index a website, send me a message that looks something like this:\n\n"
    reply = reply + bot_name + ", [index,spider,submit,store,archive,get] https://www.example.com/foo.html\n\n"
    reply = reply + "The search engines I am configured for are:\n"
    for engine in search_engines:
        reply = reply + "* " + engine.split(',')[2] + "\n"
    send_message_to_user(reply)
    return

# run_external_scripts(url): Function that takes two arguments, a string
#   containing one or more utilities to shell out to, and a URL to pass to
#   each one as an argument.  Returns True if the script returns zero (success)
#   and False if the script returns non-zero (failure).
def run_external_scripts(scripts, url):
    logging.debug("Entered run_external_scripts().")
    logging.debug("Value of url: " + str(url))

    script = None
    process = None

    for script in scripts:
        # subprocess.run() seems to work most reliably when you give it an array
        # containing the command to run and all of its arguments.
        args = script.split()

        # Append the URL to the array of arguments.
        args.append(url)
        logging.debug("Value of args: " + str(args))

        # Run the command.
        logging.debug("Executing command.")
        process = subprocess.run(args)
        logging.debug("Script returned " + str(process.returncode) + ".")

        # Test the return code from the script.
        logging.debug("Value of process.returncode: " + str(process.returncode))
        if process.returncode == 0:
            send_message_to_user("Successfully executed script " + script + ".")
        else:
            send_message_to_user("Script " + script + " returned an error.")

    logging.debug("Exiting run_external_scripts().")
    return

# Core code...
# Set up the command line argument parser.
argparser = argparse.ArgumentParser(description="A bot that polls a message queue for search requests, parses them, and submits them to one or more search engines for indexing.")

# Set the default config file and the option to set a new one.
argparser.add_argument("--config", action="store",
    default="./web_index_bot.conf")

# Loglevels: critical, error, warning, info, debug, notset.
argparser.add_argument("--loglevel", action="store",
    help="Valid log levels: critical, error, warning, info, debug, notset.  Defaults to info.")

# Time (in seconds) between polling the message queues.
argparser.add_argument("--polling", action="store", help="Default: 10 seconds")

# Parse the command line arguments.
args = argparser.parse_args()
if args.config:
    config_file = args.config

# Read the options in the configuration file before processing overrides on the
# command line.
config = configparser.ConfigParser()
if not os.path.exists(config_file):
    logging.error("Unable to find or open configuration file " +
        config_file + ".")
    sys.exit(1)
config.read(config_file)

# Get the URL of the message queue to contact.
server = config.get("DEFAULT", "queue")

# Get the names of the message queues to report to.
bot_name = config.get("DEFAULT", "bot_name")

# Construct the full message queue URL.
message_queue = server + bot_name

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

# Set the loglevel from the override on the command line.
if args.loglevel:
    loglevel = set_loglevel(args.loglevel.lower())

# Configure the logger.
logging.basicConfig(level=loglevel, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

# Set the message queue polling time from override on the command line.
if args.polling:
    polling_time = args.polling

# Load the list of search engines' URLs to submit other URLs to.
for i in config.options("search engines"):
    if "engine" in i:
        search_engines.append(config.get("search engines", i))

# If there are any external scripts defined in the config file, load them.
if config.has_section("scripts"):
    logging.info("The optional 'scripts' section exists.")
    for i in config.options("scripts"):
        if "script" in i:
            logging.info("Found external script: " + i)
            external_scripts.append(config.get("scripts", i))
else:
    # Nothing to do here, it's an optional configuration setting.
    logging.info("Didn't find any external scripts.")
    pass

# Get user-defined doing-stuff text if defined in the config file.
try:
    user_text = config.get("DEFAULT", "user_text")
except:
    # Nothing to do here, it's an optional configuration setting.
    pass

# Get additional user text if defined in the config file.
try:
    user_acknowledged = config.get("DEFAULT", "user_acknowledged")
except:
    # Nothing to do here, it's an optional configuration setting.
    pass

# Debugging output, if required.
logging.info("Everything is set up.")
logging.debug("Values of configuration variables as of right now:")
logging.debug("Configuration file: " + config_file)
logging.debug("Server to report to: " + server)
logging.debug("Message queue to report to: " + message_queue)
logging.debug("Bot name to respond to search requests with: " + bot_name)
logging.debug("Time in seconds for polling the message queue: " +
    str(polling_time))
logging.debug("Search engines available to submit URLs to:")
for i in search_engines:
    logging.debug("\t" + i)
if user_text:
    logging.debug("User-defined help text: " + user_text)
if user_acknowledged:
    logging.debug("User-defined command acknowledgement text: " + user_acknowledged)
if external_scripts:
    logging.debug("User-defined external scripts:")
    for i in external_scripts:
        logging.debug("\t" + i)

# Try to contact the XMPP bridge.  Keep trying until you reach it or the
# system shuts down.
logging.info("Trying to contact XMPP message bridge...")
while True:
    try:
        send_message_to_user(bot_name + " now online.")
        logging.info("Success.")
        break
    except:
        logging.warning("Unable to reach message bus.  Going to try again in %s seconds." % polling_time)
        time.sleep(float(polling_time))

# Go into a loop in which the bot polls the configured message queue with each
# of its configured names to see if it has any search requests waiting for it.
logging.debug("Entering main loop to handle requests.")
while True:
    index_request = None
    index_result = None

    # Check the message queue for index requests.
    try:
        logging.debug("Contacting message queue: " + message_queue)
        request = requests.get(message_queue)
    except:
        logging.warning("Connection attempt to message queue timed out or failed.  Going back to sleep to try again later.")
        time.sleep(float(polling_time))
        continue

    # Test the HTTP response code.
    # Success.
    if request.status_code == 200:
        logging.debug("Message queue " + bot_name + " found.")

        # Extract the index request.
        index_request = json.loads(request.text)
        logging.debug("Value of index_request: " + str(index_request))
        index_request = index_request['command']

        # Parse the index request.
        index_request = parse_index_request(index_request)

        # If the index request comes back None (i.e., it wasn't well formed)
        # throw an error and bounce to the top of the loop.
        if not index_request:
            time.sleep(float(polling_time))
            continue

        # If the user is requesting help, assemble a response and send it back
        # to the server's message queue.
        if index_request.lower() == "help":
            online_help()
            continue

        # Submit the index request to the configured search engines.
        if user_acknowledged:
            send_message_to_user(user_acknowledged)
        else:
            reply = "Submitting your index request now.  Please stand by."
            send_message_to_user(reply)
        index_result = submit_for_indexing(index_request)

        # MOOF MOOF MOOF - detect the use case where there are no search
        # engines defined.  Because someone might want to use this bot only
        # to run utilities or scripts.

        # If something went wrong...
        if not index_result:
            logging.warning("Something went wrong when submitting the URL for indexing.")
            reply = "Something went wrong when I submitted the URL for indexing.  Check the shell I'm running in for more details."
            send_message_to_user(reply)

        # If there are any external scripts to run, execute each one in
        # sequence.
        if external_scripts:
            reply = "Passing URL to external utilities..."
            send_message_to_user(reply)
            run_external_scripts(external_scripts, index_request)

        # Reply that it was successful.
        reply = "Your URL has been submitted to all of the search engines and archives I know about."
        send_message_to_user(reply)

    # Message queue not found.
    if request.status_code == 404:
        logging.info("Message queue " + bot_name + " does not exist.")

    # Sleep for the configured amount of time.
    time.sleep(float(polling_time))

# Fin.
sys.exit(0)
