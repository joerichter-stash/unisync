Unisync
-------
A hackable inotify daemon for Unison..


Features
--------
Unisync.py is a daemon that uses inotify to detect changes in the local
unison root and employs the venerable file synchronizer unison to
do the real sync.

On start, it runs a full-sync. After that, only localy changed files
are syncronized, unless a full-sync is triggered with sigalarm.


Setup
-----
`sudo apt install python3 unison python3-pyinotify`

*optionally for onscreen notifications:*

`sudo apt install xosd-bin`

* Setup unison profile in $HOME/.unison/<profile>.prf
* It is possible to create a local root with links to the directories and files that should be syncronized
* Run initial sync with unison


Limitations
-----------
* Unisync.py doesn't detect live changes at the remote root. However
unison is able to synchronize bidirectional if a full-sync is triggered.
  * A full-sync can be triggered by sending an alarm signal to the unisync.py process:
     `pkill -ALRM unisync.py` (that can easily be used from a keyboard shortcut)

* Only links directly below the root directory are watched by unisync.py
* Unison must be configured with the _follow property_ to follow specific links to sync their targets
  (e.g.: `follow = Name link_*` to follow all links with the prefix `link_`)



Troubleshooting
---------------
* Make sure to use the same unison version on all devices, otherwise
  unisons binary exchange format may be incompatible.
* For Ubuntu you can also download and use a specific deb-package from
  debian if compatibility with other debian based distributions is required
  (like Raspbian).


TODO
----

* Sync on server-update: Broker service: publish last modifcation of state-file
    * .unison/arXYZ -> roots in line 2
    * filename calculation:
        * 'unison -ignore 'Regex .*' -showarchive'
        * [update.ml:232]

* (GUI with status icon)

