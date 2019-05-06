#!/usr/bin/python2.7
import sys
#It shouldn't be a surprise that pjsua wouldn't be available on the local machine.
#pylint: disable=import-error
import pjsua as pj
from time import sleep
from os import listdir, getenv
#It also shouldn't be a surprise that certain members of the signal library wouldn't be available on certain OSes (Windows).
#pylint: disable=no-name-in-module
from signal import signal, SIGHUP, SIGINT, SIGTERM
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
##   with the appropriate adjustment to pjsip-apps/src/python/_pjsua.c line 2515, in the definition for
##   PyObject py_pjsua_playlist_create(self, args): pj_str_t files[64];
##   A possible idea would be to make this configurable.
##
## If you can get this working using PJSUA2, a pull request would be greatly appreciated.

# Utility classes, used basically as enums or generics
class State:
	lib=None
	running=False
	def stop(self):
		self.running=False
class PJStates:
	init=0
	deinit=1
class SIPStates:
	ringing=180
	answer=200
#Utility and state definitions
state=State()
# Logging
def PJLog(level, line, length):
	Log(level+1, "pjsip", line)
def Log(level, source, line, error=False):
	pfx='*'
	if error:
		pfx='!'
	print("%s %s: %s" % (pfx*level, source, line))
	sys.stdout.flush()
# Signal handling
def sighandle(_signo, _stack_frame):
	global state
	Log(1, "sighandler", "caught signal %s" % _signo)
	if _signo == 1:
		#SIGHUP
		Log(1, "sighandler", "SIGHUP invoked playlist reload")
		MediaLoadPlaylist()
	elif _signo == 2:
		#SIGINT
		Log(1, "sighandler", "SIGINT invoked current call flush")
		state.lib.hangup_all()
	elif _signo == 15:
		#SIGTERM
		Log(1, "sighandler", "SIGTERM invoked app shutdown")
		state.stop()
	pass

# Classes
# Account Callback class
class AccountCb(pj.AccountCallback):
	def __init__(self, account=None):
		pj.AccountCallback.__init__(self, account)

	def on_incoming_call(self, call):
		Log(2, "event-call-in", "caller %s dialled in" % call.info().remote_uri)
		call.set_callback(CallCb(call))
		#Answer call with SIP/2.0 180 RINGING
		#This kicks in the EARLY media state, allowing us to initialise the playlist before the call connects
		call.answer(SIPStates.ringing)
# Call Callback class
class CallCb(pj.CallCallback):
	def __init__(self, call=None):
		pj.CallCallback.__init__(self, call)

	def create_media(self):
		global state
		self.playlist=state.playlist
		shuffle(self.playlist)
		self.instmedia=state.lib.create_playlist(
			loop=True, filelist=self.playlist, label="trashtalklist")
		self.slotmedia=state.lib.playlist_get_slot(self.instmedia)
		Log(4, "call-media-create", "created playlist for current call")
	def connect_media(self):
		global state
		self.slotcall=self.call.info().conf_slot
		state.lib.conf_connect(self.slotmedia, self.slotcall)
		Log(4, "call-media-connect", "connected playlist media endpoint to call")
	def disconnect_media(self):
		global state
		state.lib.conf_disconnect(self.slotmedia, self.slotcall)
		Log(4, "call-media-disconnect", "disconnected playlist media endpoint from call")
	def destroy_media(self):
		global state
		state.lib.playlist_destroy(self.instmedia)
		self.instmedia=None
		self.slotmedia=None
		self.playlist=None
		Log(4, "call-media-destroy", "destroyed playlist endpoint and object")

	def on_state(self):
		global state
		Log(2, "event-state-change", "SIP/2.0 %s (%s), call %s in call with party %s" % 
			(self.call.info().last_code, self.call.info().last_reason,
			self.call.info().state_text, self.call.info().remote_uri))
		#EARLY media state allows us to init the playlist while the call establishes
		if self.call.info().state == pj.CallState.EARLY:
			self.create_media()
			Log(3, "event-call-state-early", "initialised new trashtalk playlist instance")
			#answer the call once playlist is prepared
			self.call.answer(SIPStates.answer)
		#CONFIRMED state indicates the call is connected
		elif self.call.info().state == pj.CallState.CONFIRMED:
			Log(3, "event-call-state-confirmed", "answered call")
			self.connect_media()
			Log(3, "event-call-conf-joined", "joined trashtalk to call")
		#DISCONNECTED state indicates the call has ended (whether on our end or the caller's)
		elif self.call.info().state == pj.CallState.DISCONNECTED:
			Log(3, "event-call-state-disconnected", "call disconnected")
			self.disconnect_media()
			self.destroy_media()
			Log(3, "event-call-conf-left", "removed trashtalk instance from call and destroyed it")

	def on_dtmf_digit(self, digit):
		global state
		Log(3, "dtmf-digit", "received DTMF signal: %s" % digit)
		if digit == '*':
			self.disconnect_media()
			self.destroy_media()
			self.create_media()
			self.connect_media()

	#I'm not sure what this is for, as all media handling is actually done within the SIP events above
	def on_media_state(self):
		if self.call.info().media_state == pj.MediaState.ACTIVE:
			Log(4, "event-media-state-change", "Media State transitioned to ACTIVE")
		else:
			Log(4, "event-media-state-change", "Media State transitioned to INACTIVE")

# Main logic functions
def PJControl(action):
	global state
	if action == PJStates.init:
		state.lib=pj.Lib()
		state.cfg_ua=pj.UAConfig()
		state.cfg_md=pj.MediaConfig()
		state.cfg_ua.max_calls, state.cfg_ua.user_agent = 32, "TrashTalker/1.0"
		state.cfg_md.no_vad, state.cfg_md.enable_ice = True, False
		state.lib.init(
			ua_cfg=state.cfg_ua,
			media_cfg=state.cfg_md,
			log_cfg=pj.LogConfig(
				level=state.LOG_LEVEL,
				callback=PJLog
			)
		)
		state.lib.set_null_snd_dev()
		state.lib.start(with_thread=True)
		state.transport=state.lib.create_transport(
			pj.TransportType.UDP,
			pj.TransportConfig(state.port)
		)
		state.account=state.lib.create_account_for_transport(
			state.transport,
			cb=AccountCb()
		)
		state.uri="sip:%s:%s" % (state.transport.info().host, state.transport.info().port)
	elif action == PJStates.deinit:
		state.lib.hangup_all()
		# allow time for cleanup before destroying objects
		state.lib.handle_events(timeout=250)
		try:
			state.account.delete()
			state.lib.destroy()
			state.lib=state.account=state.transport=None
		except AttributeError:
			Log(1, "deinit", "AttributeError when clearing down pjsip, this is likely fine", error=True)
			pass
		except pj.Error as e:
			Log(1, "deinit", "pjsip error when clearing down: %s" % str(e), error=True)
			pass

def WaitLoop():
	global state
	while state.running:
		sleep(0.2)

def MediaLoadPlaylist():
	Log(3, "playlist-load", "loading playlist files")
	global state
	if not state.source.endswith('/'):
		Log(4, "playlist-load", "appending trailing / to TT_MEDIA_SOURCE")
		state.source="%s/" % state.source
	state.playlist=listdir(state.source)
	state.playlist[:]=[state.source+file for file in state.playlist]
	assert (len(state.playlist) > 1), "playlist path %s must contain more than one audio file" % state.source
	Log(3, "playlist-load",
		"load playlist from %s, got %s files" % (state.source, len(state.playlist)))

def main():
	global state
	Log(1, "init", "initialising trashtalker")
	state.LOG_LEVEL=int(getenv('TT_LOG_LEVEL', 0))
	#TT_MEDIA_SOURCE and TT_LISTEN_PORT can be configured via env. variables
	state.source=getenv('TT_MEDIA_SOURCE', '/opt/media/')
	state.port=int(getenv('TT_LISTEN_PORT', 55060))
	state.running=True
	signal(SIGHUP, sighandle)
	signal(SIGINT, sighandle)
	signal(SIGTERM, sighandle)
	assert state.source.startswith('/'), "Environment variable TT_MEDIA_PATH must be an absolute path!"
	try:
		MediaLoadPlaylist()
	except:
		Log(2, "playlist-load", "exception encountered while loading playlist from path %s" % state.source, error=True)
		raise Exception("Unable to load playlist")
	try:
		PJControl(PJStates.init)
	except:
		Log(2, "pj-init", "Unable to initialise pjsip library; please check media path and SIP listening port are correct", error=True)
		raise Exception("Unable to initialise pjsip library; please check media path and SIP listening port are correct")
	Log(1, "init-complete", "trashtalker listening on uri %s and serving %s media items from %s" % (state.uri, len(state.playlist), state.source))
	try:
		WaitLoop()
	except pj.Error as e:
		Log(2, "pjsip-error", "trashtalker encountered pjsip exception %s" % str(e), error=True)
		state.stop()
		pass
	except KeyboardInterrupt:
		state.stop()
		pass
	Log(1, "deinit", "main loop exited, shutting down")
	PJControl(PJStates.deinit)
	Log(1, "deinit-complete", "trashtalker has shut down")

if __name__ == "__main__":
	main()
