#!/usr/bin/python2.7
import sys
import pjsua as pj
from time import sleep
from os import listdir, getenv
from signal import signal, SIGTERM
from random import shuffle

## NOTE:
## This script is designed to run either on the same machine or firewalled/segregated network segment
##   as the telephony appliance(s) that will use it. While there should be no security risk to doing so,
##   you should not have the SIP endpoint exposed by this application reachable on the public internet.
## This script should be configured to run automatically, and your telephony appliance should be configured
##   to treat it as a no-authentication or "IP-based authentication" SIP trunk. Any number or name will
##   be recognised and answered automatically by this script.
##
## This script uses the PJSUA library which is officially deprecated
## The reason for this is that I couldn't get this to work with equivalent code for PJSUA2.
## At time of publishing, the only library version of pjsua available in the repos for Debian 9
##   is the deprecated PJSUA (python-pjsua)
## Please also be aware that, by default, playlist length is limited to 64 items. I can find no reason
##   for this limitation, and it is specific to the python bindings for the PJSUA library.
## If you'd like to have a playlist longer than 64 items, you will need to recompile python-pjsua
##   with the appropriate adjustment to _pjsua.c line 2515
##
## If you can get this working using PJSUA2, a pull request would be greatly appreciated.

# Configuration
LOG_LEVEL=0
# You can have multiple copies of this script serving different playlists by simply duplicating it
#   ensuring you change the sourcepath and sipport accordingly.
#TODO: make this configurable via a standard config file.
sourcepath=getenv('TT_MEDIA_SOURCE', '/opt/media/')
sipport=getenv('TT_LISTEN_PORT', 5062)
# End configuration

# Application scaffolding
# logger functions
def pjlog(level, str, len):
	olog(level+1, "pjsip", str)
#print() is used over bare print because pylint yells at me if I use bare print
def elog(sev, source, line):
	print("%s %s: %s" % ("!"*sev, source, line))
	sys.stdout.flush()
def olog(sev, source, line):
	print("%s %s: %s" % ("*"*sev, source, line))
	sys.stdout.flush()
#SIGTERM handler; could be expanded to handle SIGKILL, SIGHUP, SIGUSR1, etc.
#TODO: handle SIGHUP or SIGUSR1 for live-relaoding playlist
def sighandle(_signo, _stack_frame):
	elog(1, "sighandler", "caught signal %s inside frame %s, closing main loop" % (_signo, _stack_frame))
	global mainloop
	mainloop=False
	pass

# Classes
class SIPStates:
	ringing=180
	answer=200
# Account Callback class
class AccountCb(pj.AccountCallback):
	def __init__(self, account=None):
		pj.AccountCallback.__init__(self, account)

	def on_incoming_call(self, call):
		olog(2, "event-call-in", "caller %s dialled in" % call.info().remote_uri)
		call.set_callback(CallCb(call))
		#brief delay between ringing and connected means we can do playlist setup without a period of silence
		call.answer(SIPStates.ringing)
# Call Callback class
class CallCb(pj.CallCallback):
	def __init__(self, call=None):
		pj.CallCallback.__init__(self, call)

	def on_state(self):
		olog(3, "event-state-change", "SIP/2.0 %s (%s), call %s in call with party %s" % 
			(self.call.info().last_code, self.call.info().last_reason,
			self.call.info().state_text, self.call.info().remote_uri))
		#call states not handled so far: CONNECTING
		if self.call.info().state == pj.CallState.EARLY:
			global files
			self.playlist=files
			shuffle(self.playlist)
			self.playlist_instance=pj.Lib.instance().create_playlist(
				loop=True, filelist=self.playlist, label="trashtalklist")
			self.playlistslot=pj.Lib.instance().playlist_get_slot(self.playlist_instance)
			olog(4, "event-call-state-early", "initialised new trashtalk playlist instance")
			#answer the call once playlist is prepared
			self.call.answer(SIPStates.answer)
		elif self.call.info().state == pj.CallState.CONFIRMED:
			olog(3, "event-call-state-confirmed", "answered call")
			self.confslot=self.call.info().conf_slot
			pj.Lib.instance().conf_connect(self.playlistslot, self.confslot)
			olog(3, "event-call-conf-joined", "joined trashtalk to call")
		elif self.call.info().state == pj.CallState.DISCONNECTED:
			olog(3, "event-call-state-disconnected", "call disconnected")
			pj.Lib.instance().conf_disconnect(self.playlistslot, self.confslot)
			pj.Lib.instance().playlist_destroy(self.playlist_instance)
			olog(3, "event-call-conf-left", "removed trashtalk instance from call and destroyed it")

	def on_media_state(self):
		if self.call.info().media_state == pj.MediaState.ACTIVE:
			olog(4, "event-media-state-change", "Media State transitioned to ACTIVE")
		else:
			olog(4, "event-media-state-change", "Media State transitioned to INACTIVE")

# Main logic functions
def PjInit():
	global lib
	global LOG_LEVEL
	lib=pj.Lib()
	cfg_ua=pj.UAConfig()
	#TODO: make max_calls configurable?
	cfg_ua.max_calls=32
	cfg_ua.user_agent="TrashTalker/1.0"
	cfg_media=pj.MediaConfig()
	cfg_media.no_vad=True
	cfg_media.enable_ice=False
	lib.init(ua_cfg=cfg_ua, media_cfg=cfg_media,
		log_cfg=pj.LogConfig(level=LOG_LEVEL, callback=pjlog))
	lib.set_null_snd_dev()
	lib.start(with_thread=True)

def PjMediaInit():
	global transport
	global acct
	global sipuri
	global sipport
	global lib
	transport=lib.create_transport(pj.TransportType.UDP,
		pj.TransportConfig(sipport))
	acct=lib.create_account_for_transport(transport, cb=AccountCb())
	sipuri="sip:%s:%s" % (transport.info().host, transport.info().port)

def TrashTalkerInit():
	global mainloop
	while mainloop:
		sleep(0.2)

def PjDeinit():
	global transport
	global acct
	global sipport
	global lib
	lib.hangup_all()
	# allow time for cleanup before destroying objects
	lib.handle_events(timeout=250)
	try:
		acct.delete()
		lib.destroy()
		lib=None
		acct=None
		transport=None
	except AttributeError:
		elog(1, "deinit", "AttributeError when clearing down pjsip, this is likely fine")
		pass
	except pj.Error as e:
		elog(1, "deinit", "pjsip error when clearing down: %s" % str(e))
		pass

def loadplaylist():
	olog(2, "playlist-load", "loading playlist files")
	global sourcepath
	if not sourcepath.endswith('/'):
		olog(1, "playlist-load", "appending trailing / to TT_MEDIA_SOURCE")
		sourcepath="%s/" % sourcepath
	global files
	files=listdir(sourcepath)
	files[:]=[sourcepath+file for file in files]
	assert (len(files) > 1), "playlist path %s must contain more than one audio file" % sourcepath
	olog(1, "playlist-load",
		"load playlist from %s, got %s files" % (sourcepath, len(files)))

def main():
	olog(1, "init", "initialising trashtalker")
	global mainloop
	global files
	global sipuri
	global sourcepath
	mainloop=True
	signal(SIGTERM, sighandle)
	assert sourcepath.startswith('/'), "Environment variable TT_MEDIA_PATH must be an absolute path!"
	try:
		loadplaylist()
	except:
		elog(1, "playlist-load", "exception encountered while loading playlist from path %s" % sourcepath)
		raise Exception("Unable to load playlist")
	try:
		PjInit()
	except:
		elog(1, "pj-init", "Unable to initialise pjsip library")
		raise Exception("Unable to initialise pjsip library")
	try:
		PjMediaInit()
	except:
		elog(1, "pj-media-init", "Unable to initialise pjsip media or transport")
		raise Exception("Unable to initialise pjsip media or transport")
	olog(1, "init-complete", "trashtalker listening on uri %s and serving media from %s" % (sipuri, sourcepath))
	try:
		TrashTalkerInit()
	except pj.Error as e:
		elog(1, "pjsip-error", "trashtalker encountered pjsip exception %s" % str(e))
		mainloop=False
		pass
	except KeyboardInterrupt:
		mainloop=False
		pass
	olog(1, "deinit", "main loop exited, shutting down")
	PjDeinit()
	olog(1, "deinit-complete", "trashtalker has shut down")


lib=None
acct=None
transport=None
sipuri=None
mainloop=False
files=()

if __name__ == "__main__":
	main()