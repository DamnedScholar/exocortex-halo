#!/usr/bin/env python2
# -*- coding: utf-8 -*-
# vim: set expandtab tabstop=4 shiftwidth=4 :

# This is my first serious attempt at writing an IRC bot in Python.  It uses
#   the Python module called irc (https://pythonhosted.org/irc/), which
#   implements the IRC protocol natively, and also uses MegaHAL as its
#   conversation engine.  Don't expect this to be anything major, I'm just
#   playing around to find good and bad ways of doing this.

# By: The Doctor <drwho at virtadpt dot net>

# License: GPLv3

# v1.0 - Initial release.

# TO-DO:
# - SSL/TLS support.
# - Make DixieBot.long_word_ratio configurable?

# Load modules.
# Needed because we're doing floating point division in a few places.
from __future__ import division

from megahal import *

import argparse
import ConfigParser
import irc.bot
import irc.strings
import logging
import os
import random
import socket
import sys
import time

# Constants.

# Global variables.
# Path to the configuration file and handle to a ConfigParser instance.
config_file = "dixie_flatline_bot.conf"
config = ""

# The IRC server, port, nick, and channel to default to.
irc_server = ""
irc_port = 6667
nick = "McCoyPauley"
channel = ""

# The nick of the bot's owner.
owner = ""

# How many backward chain links to run text through.  Defaults to three.
order = 3

# The location of the database the Markov model data is kept in.  This defaults
# to ./.pymegahal-brain, per the MegaHAL python module's default.
brainfile = "./.pymegahal-brain"

# Handle for a MegaHAL brain object.
brain = ""

# In case the user wants to train from a corpus to initialize the Markov brain,
# this will be a full path to a training file.
training_file = ""

# The log level for the bot.  This is used to configure the instance of logger.
loglevel = ""

# Classes.
# This is an instance of irc.bot which connects to an IRC server and channel
#   and shadows its owner.
class DixieBot(irc.bot.SingleServerIRCBot):
    # Class-level constants which form static attributes.
    # Criteria for which the bot will learn from its owner:
    # - Four or more letters
    # - Three or more words
    # - No lone numbers
    min_words_per_line = 3
    min_letters_per_word = 4

    # The percentage of long words in a line's words.
    long_word_ratio = 0.55

    # Class-level variables which form attributes.
    channel = ""
    nick = ""
    owner = ""

    # Reference to the Markov brain.
    brain = ""

    # Methods on the connection object to investigate:
    # connect() - Connect to a server?
    # connected() - 
    # disconnect() -
    # get_nickname() - 
    # get_server_name() - 
    # info() - 
    # ircname() - 
    # is_connected() - See if the connection is still up?
    # part() - Leave channel?
    # privmsg() - Send privmsg?
    # quit() - Terminate IRC connection?
    # reconnect() - Reconnect to server?
    # send_raw() - 
    # stats() - 
    # time() - 

    def __init__(self, channel, nickname, server, port, nick, owner, brain):
        # Initialize the class' attributes.
        self.channel = channel
        self.nick = nick
        self.owner = owner
        self.brain = brain

        # Initialize an instance of this class by running the parent class'
        # Default initializer method.
        # [(server, port)] can be a list of one or more (server, port) tuples
        # because it can connect to more than one at once.
        # The other two arguments are the bot's nickname and realname.
        irc.bot.SingleServerIRCBot.__init__(self, [(server, port)], nick, nick)

    # This method fires if the configured nickname is already in use.  If that
    # happens, change the bot's nick slightly.
    # Note that the name of this method is specifically what the irc module
    # looks for.
    def on_nicknameinuse(self, connection, event):
        connection.nick(connection.get_nickname() + "_")

    # This method fires when the server accepts the bot's connection.  It joins
    # the configured channel.
    def on_welcome(self, connection, event):
        connection.join(self.channel)

    # This method would fire when the bot receives a private message.  I don't
    # have anything for this yet so it's a no-op.
    def on_privmsg(self, connection, event):
        pass

    # This method fires every time a public message is posted to an IRC
    # channel.  Technically, 'line' should be 'event' but I'm just now getting
    # this module figured out...
    def on_pubmsg(self, connection, line):

        # IRC nick that sent a line to the channel.
        sending_nick = line.source.split("!~")[0]

        # See if the line fits the criteria for whether or not to learn from
        # the line.  Start with whether or not there are enough words per
        # line.
        line = line.arguments[0]
        words_in_line = 0
        if line.split(':')[0] == self.nick:
            words_in_line = len(line.split(' ')) - 1
            words_in_line -= 1
        else:
            words_in_line = len(line.split(' '))
        logger.debug("Words in line: " + str(words_in_line))

        # If the line doesn't have enough words, skip it.
        if words_in_line < self.min_words_per_line:
            logger.debug("Line isn't long enough.")
            return

        # Count the number of letters in each word of the sentence.  If at
        # least 75% are longer than four letters, learn from the sentence.
        long_words = 0
        for word in line.split(' '):
            # Pre-emptively clean up the word a little.
            word = word.strip(',')
            word = word.strip('.')
            word = word.strip(';')
            word = word.strip()

            if len(word) >= self.min_letters_per_word:
                long_words += 1
        logger.debug("Number of long words found in line: " + str(long_words))

        # If the ratio of long words to short words in the line is less than
        # 3/5, skip it.
        if (long_words / words_in_line) < self.long_word_ratio:
            logger.debug("Line wasn't long enough to learn from.")
            return

        # If the line is from the bot's owner, learn from it and then decide
        # whether to respond or not.
        if sending_nick == self.owner:
            logger.debug("Learning from text from the bot's owner.")
            self.brain.learn(line)
            self.brain.sync()
            roll = random.randint(1, 10)
            if roll == 1:
                logger.debug("Posting a response to the channel.")
                reply = self.brain.get_reply_nolearn(line)

                # connection.privmsg() can be used to send text to either a
                # channel or a user.
                connection.privmsg(self.channel, reply)
            return

        # If the line is not from the bot's owner, decide randomly if the bot
        # should learn from it, or learn from and respond to it.
        roll = random.randint(1, 10)
        if roll == 1:
            logger.debug("Learning from the last line seen in the channel.")
            self.brain.learn(line)
            self.brain.sync()
            return
        if roll == 2:
            logger.debug("Learning from the last line seen in the channel and responding to it.")
            reply = self.brain.get_reply(line)
            self.brain.sync()
            connection.privmsg(channel, reply)
            return

# Functions.
# Figure out what to set the logging level to.  There isn't a straightforward
# way of doing this because Python uses constants that are actually integers
# under the hood, and I'd really like to be able to do something like
# loglevel = 'logging.' + loglevel
# I can't have a pony, either.  Takes a string, returns a Python loglevel.
def process_loglevel(loglevel):
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

# Core code...
# Set up a command line argument parser, because that'll make it easier to play
# around with this bot.  There's no sense in not doing this right at the very
# beginning.
argparser = argparse.ArgumentParser(description="My first attempt at writing an IRC bot.  I don't yet know what I'm going to make it do.  For starters, it has an integrated Markov brain so it can interact with other people in the channel (and occasionally learn from them).")

# Set the default configuration file and command line option to specify a
# different one.
argparser.add_argument('--config', action='store',
    default='dixie_flatline_bot.conf', help="Path to a configuration file for this bot.")

# Set the IRC server.
argparser.add_argument('--server', action='store',
    help="The IRC server to connect to.  Mandatory.")

# Set the port on the IRC server to connect to (defaults to 6667/tcp).
argparser.add_argument('--port', action='store', default=6667,
    help="The port on the IRC server to connect to.  Defaults to 6667/tcp.")

# Set the nickname the bot will log in with.
argparser.add_argument('--nick', action='store', default='McCoyPauley',
    help="The IRC nick to log in with.  Defaults to MyBot.  You really should change this.")

# Set the channel the bot will attempt to join.
argparser.add_argument('--channel', action='store',
    help="The IRC channel to join.  No default.  Specify this with a backslash (\#) because the shell will interpret it as a comment and mess with you otherwise.")

# Set the nick of the bot's owner, which it will learn from preferentially.
argparser.add_argument('--owner', action='store',
    help="This is the nick of the bot's owner, so that it knows who to take commands and who to train its Markov brain from.")

# Set the number of backward links the Markov engine will look when generating
# responses (defaults to 3).
argparser.add_argument('--order', action='store', default=3,
    help="The number of backward links the Markov engine will look when generating responses (defaults to 3).  Once the brain is built, this can no longer be changed.")

# Path to the MegaHAL brain database.  If this file doesn't exist it'll be
# created, and unless a file to train the bot is supplied in another command
# line argument it'll have to train itself very slowly.
argparser.add_argument('--brain', action='store',
    help="Path to the MegaHAL brainfile.  If this file doesn't exist it'll be created, and you'll have to supply an initial training file in another argument.")

# Path to a training file for the MegaHAL brain.
argparser.add_argument('--trainingfile', action='store',
    help="Path to a file to train the Markov brain with if you haven't done so already.  It can be any text file so long as it's plain text and there is one entry per line.  If a brain already exists, training more is probably bad.  If you only want the bot to learn from you, chances are you don't want this.")

# Loglevels: critical, error, warning, info, debug, notset.
argparser.add_argument('--loglevel', action='store', default='logging.INFO',
    help='Valid log levels: critical, error, warning, info, debug, notset.  Defaults to INFO.')

# Parse the command line arguments.
args = argparser.parse_args()

# If a configuration file is specified on the command line, load and parse it.
config = ConfigParser.ConfigParser()
if args.config:
    config_file = args.config
    config.read(config_file)
if os.path.exists(config_file):
    # Get configuration options from the config file.
    irc_server = config.get("DEFAULT", "server")
    irc_port = config.get("DEFAULT", "port")
    nick = config.get("DEFAULT", "nick")
    channel = config.get("DEFAULT", "channel")
    owner = config.get("DEFAULT", "owner")
    brain = config.get("DEFAULT", "brain")
    loglevel = config.get("DEFAULT", "loglevel").lower()
else:
    logger.error("Unable to open configuration file " + config_file + ".")

# IRC server to connect to.
if not args.server:
    logger.fatal("ERROR: You must specify the hostname or IP of an IRC server at a minimum.")
    sys.exit(1)
else:
    irc_server = args.server

# Port on the IRC server.
if args.port:
    irc_port = args.port

# Nickname to present as.
if args.nick:
    nick = args.nick

# Channel to connect to.
if not args.channel:
    logger.fatal("ERROR: You must specify a channel to join.")
    sys.exit(1)
else:
    channel = args.channel

# Nick of the bot's owner to follow around.
if args.owner:
    owner = args.owner
else:
    logger.fatal("ERROR: You must specify the nick of the bot's owner.")
    sys.exit(1)

# Order of the Markov chains to construct.
if args.order:
    order = args.order

# If a prebuilt brainfile is specified on the command line, try to load it.
if args.brain:
    brainfile = args.brain
    if not os.path.exists(brainfile):
        logger.fatal("WARNING: The brainfile you've specified (" + brainfile + ") does not exist.")
        sys.exit(1)

# If a training file is available, grab it.
if args.trainingfile:
    training_file = args.trainingfile

# Let's not let people re-train existing Markov brains.  Because I'm tired and
# punchy.
if args.brain and args.trainingfile:
    logger.fatal("WARNING: It's a bad idea to re-train an existing brainfile with a new corpus.  I'll figure out how to do that later.")
    sys.exit(1)

# If an existing brain was specified, try to open it.  Else, create a new one
# using the training corpus.
brain = MegaHAL(order=order, brainfile=brainfile)
if training_file:
    logger.info("Training the bot's Markov brain... this could take a while...")
    brain.train(training_file)
    print "Done!"

# Figure out how to configure the logger.  Start by reading from the config
# file, then try the argument vector.
if loglevel:
    loglevel = process_loglevel(loglevel)
if args.loglevel:
    loglevel = process_loglevel(args.loglevel.lower())

# Configure the logger.
logging.basicConfig(level=loglevel, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

# Prime the RNG.
random.seed()

# Instantiate a copy of the bot class.
bot = DixieBot(channel, nick, irc_server, irc_port, nick, owner, brain)
bot.start()

# Fin.
brain.sync()
brain.close()
sys.exit(0)

