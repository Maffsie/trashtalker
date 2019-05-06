# trashtalker

Python-based script that, via SIP, plays WAV files indefinitely.

## Notes

This application was written to work in tandem with 3CX, but should fit essentially any use-case.
Any incoming call will immediately be answered, regardless of the user segment of the incoming URI.

## Installing

As noted above, this application was written to work in tandem with 3CX. As such, installation notes are geared towards the 3CX distribution of Debian Linux 9.
The general process is as follows:
* `apt update`
* `apt install -y python-pjproject`
* `wget https://git.maff.scot/maff/trashtalker/archive/v1.1.tar.gz`
* `tar xaf v1.1.tar.gz`
* `rm v1.1.tar.gz`
* `cd trashtalker`
* `mv trashtalker.py /usr/local/bin/`
* `mv trashtalker@.service /etc/systemd/system/`
* `mkdir /opt/.tt`
* `mv example.conf /opt/.tt/`
* modify the contents of example.conf to match your needs
* `systemctl enable trashtalker@example`
* `service trashtalker@example start`

Within 3CX:
* Create a new SIP trunk (country: Generic, provider: Generic SIP Trunk, main no: any number of your choice, it doesn't matter)
* Name the new trunk something of your choice
* Define the registrar and outbound proxy IPs as `127.0.0.1`
* Set the port for both of these to match the particular instance of TrashTalker you're configuring
* Leave the authentication settings to "`Do not require - IP Based`"
* Click OK to save the trunk
* Create an outbound dial route with parameters of your preference, and set the first route to be the SIP trunk you created above. Ensure you do not set any other route entries for this outbound dial route.
* Click OK to save the rule
* Place a call which matches your newly-created outbound route. You should hear your choice of media.

## See (hear) it in action

This application currently operates the PR Gnusline, which can be dialled at the following number(s):
* +44 (0) 1337 515 404
* +1 (412) 406-9141
