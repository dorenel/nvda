# A part of NonVisual Desktop Access (NVDA)
# Copyright (C) 2020 NV Access Limited
# This file may be used under the terms of the GNU General Public License, version 2 or later.
# For more details see: https://www.gnu.org/licenses/gpl-2.0.html

"""Logic for startupShutdownNVDA tests.
"""

from datetime import datetime as _datetime
from typing import Callable as _Callable
from robot.libraries.BuiltIn import BuiltIn
# relative import not used for 'systemTestUtils' because the folder is added to the path for 'libraries'
# imported methods start with underscore (_) so they don't get imported into robot files as keywords
from SystemTestSpy import (
	_getLib,
	_blockUntilConditionMet,
)
from SystemTestSpy.windows import waitUntilWindowFocused

# Imported for type information
from robot.libraries.Process import Process as _ProcessLib
from robot.libraries.OperatingSystem import OperatingSystem as _OpSysLib

from AssertsLib import AssertsLib as _AssertsLib

import NvdaLib as _nvdaLib
from NvdaLib import NvdaLib as _nvdaRobotLib
_nvdaProcessAlias = _nvdaRobotLib.nvdaProcessAlias

_nvdaRobot: _nvdaRobotLib = _getLib("NvdaLib")
_opSys: _OpSysLib = _getLib('OperatingSystem')
_builtIn: BuiltIn = BuiltIn()
_process: _ProcessLib = _getLib("Process")
_asserts: _AssertsLib = _getLib("AssertsLib")


def NVDA_Starts():
	""" Test that NVDA can start"""
	_process.process_should_be_running(_nvdaProcessAlias)


def quits_from_menu(showExitDialog=True):
	"""Ensure NVDA can be quit from menu."""
	spy = _nvdaLib.getSpyLib()
	_builtIn.sleep(1)
	spy.emulateKeyPress("NVDA+n")
	spy.emulateKeyPress("x", blockUntilProcessed=False)  # don't block so NVDA can exit
	if showExitDialog:
		exitTitleIndex = spy.wait_for_specific_speech("Exit NVDA")

		spy.wait_for_speech_to_finish()
		actualSpeech = spy.get_speech_at_index_until_now(exitTitleIndex)

		_asserts.strings_match(
			actualSpeech,
			"\n".join([
				"Exit NVDA  dialog",
				"What would you like to do?  combo box  Exit  collapsed  Alt plus d"
			])
		)
		_builtIn.sleep(1)  # the dialog is not always receiving the enter keypress, wait a little for it
		spy.emulateKeyPress("enter", blockUntilProcessed=False)  # don't block so NVDA can exit

	_process.wait_for_process(_nvdaProcessAlias, timeout="10 sec")
	_process.process_should_be_stopped(_nvdaProcessAlias)


def quits_from_keyboard():
	"""Ensure NVDA can be quit from keyboard."""
	spy = _nvdaLib.getSpyLib()
	spy.wait_for_specific_speech("Welcome to NVDA")  # ensure the dialog is present.
	spy.wait_for_speech_to_finish()
	_builtIn.sleep(1)  # the dialog is not always receiving the enter keypress, wait a little longer for it
	spy.emulateKeyPress("enter")

	spy.emulateKeyPress("NVDA+q")
	exitTitleIndex = spy.wait_for_specific_speech("Exit NVDA")

	spy.wait_for_speech_to_finish()
	actualSpeech = spy.get_speech_at_index_until_now(exitTitleIndex)

	_asserts.strings_match(
		actualSpeech,
		"\n".join([
			"Exit NVDA  dialog",
			"What would you like to do?  combo box  Exit  collapsed  Alt plus d"
		])
	)
	_builtIn.sleep(1)  # the dialog is not always receiving the enter keypress, wait a little longer for it
	spy.emulateKeyPress("enter", blockUntilProcessed=False)  # don't block so NVDA can exit
	_process.wait_for_process(_nvdaProcessAlias, timeout="10 sec")
	_process.process_should_be_stopped(_nvdaProcessAlias)


def test_desktop_shortcut():
	spy = _nvdaLib.getSpyLib()
	spy.emulateKeyPress("control+alt+n")
	# Takes some time to exit a running process and start a new one
	waitUntilWindowFocused("Welcome to NVDA", timeoutSecs=7)


def read_welcome_dialog():
	spy = _nvdaLib.getSpyLib()
	welcomeTitleIndex = spy.wait_for_specific_speech("Welcome to NVDA")  # ensure the dialog is present.
	spy.wait_for_speech_to_finish()
	actualSpeech = spy.get_speech_at_index_until_now(welcomeTitleIndex)

	_asserts.strings_match(
		actualSpeech,
		"\n".join([
			(
				"Welcome to NVDA  dialog  Welcome to NVDA! Most commands for controlling NVDA require you to hold "
				"down the NVDA key while pressing other keys. By default, the numpad Insert and main Insert keys "
				"may both be used as the NVDA key. You can also configure NVDA to use the Caps Lock as the NVDA "
				"key. Press NVDA plus n at any time to activate the NVDA menu. From this menu, you can configure "
				"NVDA, get help and access other NVDA functions."
			),
			"Options  grouping",
			"Keyboard layout:  combo box  desktop  collapsed  Alt plus k"
		])
	)
	_builtIn.sleep(1)  # the dialog is not always receiving the enter keypress, wait a little longer for it
	spy.emulateKeyPress("enter")


def NVDA_restarts():
	"""Ensure NVDA can be restarted from keyboard."""
	spy = _nvdaLib.getSpyLib()
	spy.wait_for_specific_speech("Welcome to NVDA")  # ensure the dialog is present.
	spy.wait_for_speech_to_finish()

	spy.emulateKeyPress("NVDA+q")
	spy.wait_for_specific_speech("Exit NVDA")

	_builtIn.sleep(0.5)  # the dialog is not always receiving the enter keypress, wait a little longer for it
	spy.emulateKeyPress("downArrow")
	spy.wait_for_specific_speech("Restart")
	spy.emulateKeyPress("enter", blockUntilProcessed=False)  # don't block so NVDA can exit
	_process.wait_for_process(_nvdaProcessAlias, timeout="10 sec")
	_process.process_should_be_stopped(_nvdaProcessAlias)
	waitUntilWindowFocused("Welcome to NVDA")


def _attemptFileRemove(filePath: str) -> bool:
	try:
		_opSys.remove_file(filePath)
		return True
	except PermissionError:
		return False


def _ensureRestartWithCrashDump(crashFunction: _Callable[[], None]):
	startTime = _datetime.utcnow()
	spy = _nvdaLib.getSpyLib()
	spy.wait_for_specific_speech("Welcome to NVDA")  # ensure the dialog is present
	spy.emulateKeyPress("enter")  # close the dialog so we can check for it after the crash
	crashFunction()
	_process.wait_for_process(_nvdaProcessAlias, timeout="3 sec")
	_process.process_should_be_stopped(_nvdaProcessAlias)
	crashOccurred, crashPath = _blockUntilConditionMet(
		getValue=lambda: _nvdaRobot.check_for_crash_dump(startTime),
		giveUpAfterSeconds=3,
	)
	if not crashOccurred:
		raise AssertionError("A crash.dmp file has not been generated after a crash")
	waitUntilWindowFocused("Welcome to NVDA")
	# prevent test failure by removing the crash dump file
	crashFileDeleted, _crashFileExists = _blockUntilConditionMet(
		getValue=lambda: _attemptFileRemove(crashPath),
		giveUpAfterSeconds=3,
	)
	_opSys.wait_until_removed(crashPath)
	if not crashFileDeleted:
		raise AssertionError("crash.dmp file could not be deleted")


def NVDA_restarts_on_crash():
	"""Ensure NVDA restarts on crash."""
	spy = _nvdaLib.getSpyLib()
	_ensureRestartWithCrashDump(spy.queueNVDAMainThreadCrash)


def NVDA_restarts_on_braille_crash():
	"""Ensure NVDA restarts on crash."""
	spy = _nvdaLib.getSpyLib()
	_ensureRestartWithCrashDump(spy.queueNVDABrailleThreadCrash)


def NVDA_restarts_on_UIAHandler_crash():
	"""Ensure NVDA restarts on crash."""
	spy = _nvdaLib.getSpyLib()
	_ensureRestartWithCrashDump(spy.queueNVDAUIAHandlerThreadCrash)
