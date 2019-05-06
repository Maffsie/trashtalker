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
	sip_ringing=180
	sip_answer=200
	def Log(level, source, line, error=False):
		pfx='*'
		if error:
			pfx='!'
		print("%s %s: %s" % (pfx*level, source, line))
		sys.stdout.flush()
	def preinit(self):
		self.Log(1, "preinit", "initialising from environment")
		self.LOG_LEVEL=int(getenv('TT_LOG_LEVEL', 0))
		self.port=int(getenv('TT_LISTEN_PORT', 55060))
		self.source=getenv('TT_MEDIA_SOURCE', '/opt/media/')
		assert self.source.startswith('/'), "TT_MEDIA_SOURCE must specify an absolute path!"
	def init(self):
		self.lib=pj.Lib()
		self.cfg_ua=pj.UAConfig()
		self.cfg_md=pj.MediaConfig()
		self.cfg_ua.max_calls, self.cfg_ua.user_agent = 32, "TrashTalker/1.0"
		self.cfg_md.no_vad, self.cfg_md.enable_ice = True, False
		self.cfg_lg=pj.LogConfig(
			level=self.LOG_LEVEL,
			callback=PJLog)
		self.lib.init(
			ua_cfg=cfg_ua,
			media_cfg=cfg_md,
			log_cfg=cfg_lg)
		self.lib.set_null_snd_dev()
		self.lib.start(
			with_thread=True)
		self.transport=self.lib.create_transport(
			pj.TransportType.UDP,
			pj.TransportConfig(self.port))
		self.account=self.lib.create_account_for_transport(
			self.transport,
			cb=AccountCb())
		self.uri="sip:%s:%s" % (self.transport.info().host, self.transport.info().port)
	def media_init(self):
		self.Log(3, "playlist-load", "loading playlist files from media path %s" % self.source)
		if not self.source.endswith('/'):
			self.Log(4, "playlist-load", "appending trailing / to TT_MEDIA_SOURCE")
			self.source="%s/" % self.source
		self.playlist=listdir(self.source)
		self.playlist[:]=[self.source+file for file in self.playlist]
		assert (len(self.playlist) > 1), "playlist path %s must contain more than one audio file" % self.source
		self.Log(3, "playlist-load", "loaded %s media items from path %s" % (len(self.playlist), self.source))
	def deinit(self):
		self.lib.hangup_all()
		self.lib.handle_events(timeout=250)
		try:
			self.account.delete()
			self.lib.destroy()
			self.lib=self.account=self.transport=None
		except AttributeError:
			self.Log(1, "deinit", "Got an AttributeError exception during shutdown.", error=True)
			pass
		except pj.Error as e:
			self.Log(1, "deinit", "Got a PJError exception during shutdown: %s" % str(e), error=True)
			pass
	def run(self):
		self.running=True
		while self.running:
			sleep(0.2)
	def stop(self):
		self.running=False
#Utility and state definitions
state=State()
# Logging
def PJLog(level, line, length):
	global state
	state.Log(level+1, "pjsip", line)
# Signal handling
def sighandle(_signo, _stack_frame):
	global state
	state.Log(1, "sighandler", "caught signal %s" % _signo)
	if _signo == 1:
		#SIGHUP
		state.Log(1, "sighandler", "SIGHUP invoked playlist reload")
		state.media_init()
	elif _signo == 2:
		#SIGINT
		state.Log(1, "sighandler", "SIGINT invoked current call flush")
		state.lib.hangup_all()
	elif _signo == 15:
		#SIGTERM
		state.Log(1, "sighandler", "SIGTERM invoked app shutdown")
		state.stop()
	pass

# Classes
# Account Callback class
class AccountCb(pj.AccountCallback):
	def __init__(self, account=None):
		pj.AccountCallback.__init__(self, account)

	def on_incoming_call(self, call):
		global state
		state.Log(2, "event-call-in", "caller %s dialled in" % call.info().remote_uri)
		call.set_callback(CallCb(call))
		#Answer call with SIP/2.0 180 RINGING
		#This kicks in the EARLY media state, allowing us to initialise the playlist before the call connects
		call.answer(state.sip_ringing)
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
		state.Log(4, "call-media-create", "created playlist for current call")
	def connect_media(self):
		global state
		self.slotcall=self.call.info().conf_slot
		state.lib.conf_connect(self.slotmedia, self.slotcall)
		state.Log(4, "call-media-connect", "connected playlist media endpoint to call")
	def disconnect_media(self):
		global state
		state.lib.conf_disconnect(self.slotmedia, self.slotcall)
		state.Log(4, "call-media-disconnect", "disconnected playlist media endpoint from call")
	def destroy_media(self):
		global state
		state.lib.playlist_destroy(self.instmedia)
		self.instmedia=None
		self.slotmedia=None
		self.playlist=None
		state.Log(4, "call-media-destroy", "destroyed playlist endpoint and object")

	def on_state(self):
		global state
		state.Log(2, "event-state-change", "SIP/2.0 %s (%s), call %s in call with party %s" % 
			(self.call.info().last_code, self.call.info().last_reason,
			self.call.info().state_text, self.call.info().remote_uri))
		#EARLY media state allows us to init the playlist while the call establishes
		if self.call.info().state == pj.CallState.EARLY:
			self.create_media()
			state.Log(3, "event-call-state-early", "initialised new trashtalk playlist instance")
			#answer the call once playlist is prepared
			self.call.answer(state.sip_answer)
		#CONFIRMED state indicates the call is connected
		elif self.call.info().state == pj.CallState.CONFIRMED:
			state.Log(3, "event-call-state-confirmed", "answered call")
			self.connect_media()
			state.Log(3, "event-call-conf-joined", "joined trashtalk to call")
		#DISCONNECTED state indicates the call has ended (whether on our end or the caller's)
		elif self.call.info().state == pj.CallState.DISCONNECTED:
			state.Log(3, "event-call-state-disconnected", "call disconnected")
			self.disconnect_media()
			self.destroy_media()
			state.Log(3, "event-call-conf-left", "removed trashtalk instance from call and destroyed it")

	def on_dtmf_digit(self, digit):
		global state
		state.Log(3, "dtmf-digit", "received DTMF signal: %s" % digit)
		if digit == '*':
			self.disconnect_media()
			self.destroy_media()
			self.create_media()
			self.connect_media()

	#I'm not sure what this is for, as all media handling is actually done within the SIP events above
	def on_media_state(self):
		global state
		if self.call.info().media_state == pj.MediaState.ACTIVE:
			state.Log(4, "event-media-state-change", "Media State transitioned to ACTIVE")
		else:
			state.Log(4, "event-media-state-change", "Media State transitioned to INACTIVE")

# Main logic functions
def main():
	global state
	#Try to pre-init
	try:
		state.preinit()
	except AssertionError as e:
		state.Log(1, "preinit", "AssertionError while pre-initialising: %s" % str(e))
		raise Exception("Unable to start up TrashTalker. Check all configuration parameters are correct, and review logs.")
	#Attach signal handlers
	signal(SIGHUP, sighandle)
	signal(SIGINT, sighandle)
	signal(SIGTERM, sighandle)
	#Try to initialise media
	try:
		state.media_init()
	except:
		state.Log(2, "playlist-load", "exception encountered while loading playlist from path %s" % state.source, error=True)
		raise Exception("Unable to load playlist")
	#Try to initialise main process; only fault here should be if the configured listening port is unavailable to us
	try:
		state.init()
	except:
		state.Log(2, "pj-init", "Unable to initialise pjsip library; please check media path and SIP listening port are correct", error=True)
		raise Exception("Unable to initialise pjsip library; please check media path and SIP listening port are correct")
	state.Log(1, "init-complete", "trashtalker listening on uri %s and serving %s media items from %s" % (state.uri, len(state.playlist), state.source))
	#Enter main loop
	try:
		state.run()
	except pj.Error as e:
		state.Log(2, "pjsip-error", "trashtalker encountered pjsip exception %s" % str(e), error=True)
		state.stop()
		pass
	except KeyboardInterrupt:
		state.stop()
		pass
	state.Log(1, "deinit", "main loop exited, shutting down")
	state.deinit()
	state.Log(1, "deinit", "trashtalker has shut down")

if __name__ == "__main__":
	main()
