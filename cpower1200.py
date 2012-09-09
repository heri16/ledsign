#!/usr/bin/env python
"""
Driver for the C-Power 1200 
Copyright 2010-2012 Michael Farrell <http://micolous.id.au/>

Requires pyserial library in order to interface, and PIL to encode images.

Current windows binaries for PIL are available from here: http://www.lfd.uci.edu/~gohlke/pythonlibs/

This library is free software: you can redistribute it and/or modify
it under the terms of the GNU Lesser General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU Lesser General Public License
along with this program.  If not, see <http://www.gnu.org/licenses/>.
"""
import serial, string
from datetime import datetime, time
from struct import pack
from time import sleep
from warnings import warn
from cStringIO import StringIO
	

CC_DIVISION = 1
CC_TEXT = 2
CC_IMAGE = 3
CC_STATIC_TEXT = 4
CC_CLOCK = 5
CC_EXIT = 6
CC_SAVE = 7
CC_PLAY_SINGLE = 8
CC_PLAY_DOUBLE = 9
CC_SET_VARIABLE = 10
CC_PLAY_SET_VARIABLE = 11

EFFECT_NONE = 0
EFFECT_OPEN_LEFT = 1
EFFECT_OPEN_RIGHT = 2
EFFECT_OPEN_HORIZ = 3
EFFECT_OPEN_VERT = 4
EFFECT_SHUTTER = 5
EFFECT_MOVE_LEFT = 6
EFFECT_MOVE_RIGHT = 7
EFFECT_MOVE_UP = 8
EFFECT_MOVE_DOWN = 9
EFFECT_SCROLL_UP = 10
EFFECT_SCROLL_LEFT = 11
EFFECT_SCROLL_RIGHT = 12

ALIGN_LEFT = 0
ALIGN_CENTRE = ALIGN_CENTER = 1
ALIGN_RIGHT = 2

# colours
RED = 1
GREEN = 2
YELLOW = 3
BLUE = 4
PURPLE = 5
CYAN = 6
WHITE = 7

PACKET_TYPE = 0x68
CARD_TYPE = 0x32
PROTOCOL_CODE = 0x7B

IMAGE_GIF = 1
IMAGE_GIF_REF = 2
IMAGE_PKG_REF = 3
IMAGE_SIMPLE = 4

SAVE_SAVE = 0
SAVE_RESET = 1

CALENDAR_GREGORIAN = 0
CALENDAR_LUNAR = 1
CALENDAR_CHINESE = 2
CALENDAR_LUNAR_SOLAR = 3

class CPower1200(object):
	"""Implementation of the C-Power 1200 protocol"""
	
	def __init__(self, port, queue=False):
		self.s = serial.Serial(port, 115200)
		self.file_id = None
		self.message_open = False
		print "opening %s" % self.s.portstr
		self.queue = bool(queue)
		self._queued_packets = []
	
	def begin_queue(self):
		self.queue = True
		self._queued_packets = []
		
	def flush_queue(self, unit_id=0xFF, confirmation=False):
		if not self.queue:
			raise AttributeError, "Cannot flush queue as it is not running in queue mode!"
		
		# FIXME: Queuing does not work correctly.
		
		# grab the current queue and clear it out.
		queued_packets = list(self._queued_packets)
		self._queued_packets = []
		
		# start processing commands.
		
		for i, packet_data in enumerate(queued_packets):
			body = pack('<BBBBBHBB', 
				PACKET_TYPE, CARD_TYPE, unit_id,
				PROTOCOL_CODE, confirmation, len(packet_data),
				i, # packet number
				len(queued_packets) - 1) # total packets - 1
			body += packet_data
			checksum = self.checksum(body)
			msg = "\xA5%s\xAE" % self._escape_data(body + checksum)
			print repr(msg)
			self.s.write(msg)
			self.s.flush()
		
	
	def _write(self, packet_data, unit_id=0xFF, confirmation=False):
		# start code    A5
		# packet type   68
		# card type     32
		# card ID       XX   or FF == all units
		# protocol code 7B
		# confirmation  00 / 01
		# packet length XX XX (uint16 le)
		# packet number XX (uint8)
		# total packets XX (uint8)
		# packet data
		# packet checksum (uint16 le)
		#     sum of each byte from "packet type" to "packet data" content
		
		if len(packet_data) > 0xFFFF:
			raise ValueError, 'Packet too long, packet fragmentation not yet implemented!'
		
		if not (0 <= unit_id <= 255):
			raise ValueError, 'Unit ID out of range (0 - 255)'
		
		if self.queue:
			self._queued_packets.append(packet_data)
			return
			
		confirmation = 0x01 if confirmation else 0x00
		body = pack('<BBBBBHBB', 
			PACKET_TYPE, CARD_TYPE, unit_id,
			PROTOCOL_CODE, confirmation, len(packet_data),
			0, # packet number
			0) # total packets - 1
		
		body += packet_data
		checksum = self.checksum(body)
		msg = self._escape_data(body + checksum)
		
		#print '%r' % msg
		self.s.write("\xA5%s\xAE" % (msg,))
		
		# before another message can be sent, you need to wait a moment
		self.s.flush()
		sleep(.1)
	
	def _escape_data(self, input):
		return input.replace('\xAA', '\xAA\x0A').replace('\xAE', '\xAA\0x0E').replace('\xA5', '\xAA\x05')
		
	def checksum(self, input):
		s = 0
		for c in input:
			s += ord(c)
		
		s &= 0xFFFF
		return pack('<H', s)
		
	def format_text(self, text='', colour=WHITE, size=0):
		"Generate formatted text"
		if not 0x00 < colour < 0x10:
			raise ValueError, "invalid colour"
		
		if not 0x00 <= size <= 0x0F:
			# TODO: Implement this as a transition from a pixel font size
			raise ValueError, "invalid size code"
		
		# colours appear to be as follows:
		#  bit 1: red
		#  bit 2: green (only on green-supporting sign)
		#  bit 3: blue  (only on full-colour sign)
		
		# the "colour / size" code has the high 4 bits as the colour,
		# and the low 4 bits as the size.
		colour_size = chr( (colour << 4) ^ size )
		
		o = ''
		for c in text.encode('ascii'):
			o += colour_size + '\0' + c
		
		return o
		
	def send_text(self, window, formatted_text, effect=EFFECT_SCROLL_LEFT, alignment=ALIGN_LEFT, speed=30, stay_time=2):
		if not 0 <= window <= 7:
			raise ValueError, "invalid window (must be 0 - 7)"
		
		packet = pack('<BBBBBH', CC_TEXT, window, effect, alignment, speed, stay_time) + formatted_text + '\0\0\0'
		
		self._write(packet)
	
	def send_static_text(self, window, text, x=0, y=0, width=64, height=16, speed=30, stay_time=2, alignment=ALIGN_LEFT, font_size=1, red=0, green=0, blue=0):
		if not 0 <= window <= 7:
			raise ValueError, "invalid window (must be 0 - 7)"
			
		packet = pack('<BBBBHHHHBBBB',
			CC_STATIC_TEXT, window,
			1, # simple text data
			alignment, x, y, width, height,
			font_size, red, green, blue) + text + '\0'
		
		# TODO: fix this.
		s._write(packet)
			
			
			
	
	def send_window(self, *windows):
		# TODO: protocol supports sending multiple window definition at once.
		# Make a way to expose this in the API.
		
		# arguments are dicts with the following keys:
		#     x: x-position of window
		#     y: y-position of window
		#     w: width of window
		#     h: height of window
		#
		# arguments are indicated in pixels.
		
		# HERE BE DRAGONS: This function call is BIG ENDIAN.
		# All the others are LITTLE ENDIAN.  Beware.
		packet = pack('>BB', CC_DIVISION, len(windows))
		for window in windows:
			packet += pack('>HHHH', window['x'], window['y'], window['w'], window['h'])
		
		self._write(packet)
	
	def send_image(self, window, image, speed=30, stay_time=2, x=0, y=0):
		"Sends an image to the sign.  Should be a PIL Image object."
		if not 0 <= window <= 7:
			raise ValueError, "invalid window (must be 0 - 7)"
			
		ibuf = StringIO()
		image.convert('I')
		
		# image.save accepts a file-like object. (undocumented)
		image.save(ibuf, 'gif')
		
		packet = pack('<BBBBHBHH',
			CC_IMAGE, window, 
			0, # mode 0 == draw
			speed, stay_time, IMAGE_GIF,
			x, y) + ibuf.getvalue()
		
		# FIXME: doesn't work.
		self._write(packet)
	
	def send_clock(self, window, stay_time=5000, calendar=CALENDAR_GREGORIAN, hour_24=True, year_4=True, multiline=True, display_year=True, display_month=True, display_day=True, display_hour=True, display_minute=True, display_second=True, display_week=False, display_pointer=False, font_size=0, red=255, green=255, blue=255, text=''):
		# (so many parameters)
		
		# pack in the format
		format = 0
		format |= 1 if hour_24 else 0
		format |= 2 if not year_4 else 0
		format |= 4 if multiline else 0
		
		# pack the display content
		content = 0
		content |= 1 if display_year else 0
		content |= 2 if display_month else 0
		content |= 4 if display_day else 0
		content |= 8 if display_hour else 0
		content |= 16 if display_minute else 0
		content |= 32 if display_second else 0
		content |= 64 if display_week else 0
		content |= 128 if display_pointer else 0
		
		# validate font size
		if not (0 <= font_size <= 7):
			raise ValueError, "font size out of range (0 - 7)"
			
		if not 0 <= window <= 7:
			raise ValueError, "invalid window (must be 0 - 7)"
			
		packet = pack('<BBHBBBBBBB',
			CC_CLOCK, window, stay_time, calendar,
			format, content, font_size, red, green, blue) + text + '\0'
		
		self._write(packet)
			
		
	
	#def show_clock
	def save(self):
		packet = pack('<BBH', CC_SAVE, SAVE_SAVE, 0)
		self._write(packet)
	
	def reset(self):
		packet = pack('<BBH', CC_SAVE, SAVE_RESET, 0)
		self._write(packet)
	
	def exit_show(self):
		packet = pack('<B', CC_EXIT)
		self._write(packet)
		
	def close(self):
		self.s.close()

if __name__ == '__main__':
	from sys import argv
	import Image
	
	s = CPower1200(argv[1])
	#s.begin_queue()
	#s.reset()
	#s.exit_show()
	
	# define two windows, one at the top and one at the bottom.
	s.send_window(dict(x=0, y=0, h=8, w=64), dict(x=0, y=8, h=8, w=64))
	
	#s.send_window(1, 0, 8, 64, 8)
	txt = s.format_text('Hello', RED, 0) + s.format_text(' World!', GREEN, 0)
	s.send_text(0, txt)
	#s.send_static_text(0, 'Hello World!')
	#img = Image.open('test.png')
	#s.send_image(0, img)
	
	s.send_clock(1, calendar=CALENDAR_GREGORIAN, multiline=False)
	
	#s.flush_queue()
	s.save()
	
