# This file is covered by the GNU General Public License.
# A part of NonVisual Desktop Access (NVDA)
# See the file COPYING for more details.
# Copyright (C) 2016-2021 NV Access Limited, Joseph Lee, Jakub Lukowicz

from comtypes import COMError
from collections import defaultdict
import textInfos
import eventHandler
import UIAHandler
from logHandler import log
import controlTypes
import ui
import speech
import api
import browseMode
from UIABrowseMode import UIABrowseModeDocument, UIADocumentWithTableNavigation, UIATextAttributeQuicknavIterator, TextAttribUIATextInfoQuickNavItem
from UIAUtils import *
from . import UIA, UIATextInfo
from NVDAObjects.window.winword import WordDocument as WordDocumentBase
from scriptHandler import script


"""Support for Microsoft Word via UI Automation."""

#: the non-printable unicode character that represents the end of cell or end of row mark in Microsoft Word
END_OF_ROW_MARK = '\x07'

class ElementsListDialog(browseMode.ElementsListDialog):

	ELEMENT_TYPES=(browseMode.ElementsListDialog.ELEMENT_TYPES[0],browseMode.ElementsListDialog.ELEMENT_TYPES[1],
		# Translators: The label of a radio button to select the type of element
		# in the browse mode Elements List dialog.
		("annotation", _("&Annotations")),
		# Translators: The label of a radio button to select the type of element
		# in the browse mode Elements List dialog.
		("error", _("&Errors")),
	)

class RevisionUIATextInfoQuickNavItem(TextAttribUIATextInfoQuickNavItem):
	attribID=UIAHandler.UIA_AnnotationTypesAttributeId
	wantedAttribValues={UIAHandler.AnnotationType_InsertionChange,UIAHandler.AnnotationType_DeletionChange,UIAHandler.AnnotationType_TrackChanges}

	@property
	def label(self):
		text=self.textInfo.text
		if UIAHandler.AnnotationType_InsertionChange in self.attribValues:
			# Translators: The label shown for an insertion change 
			return _(u"insertion: {text}").format(text=text)
		elif UIAHandler.AnnotationType_DeletionChange in self.attribValues:
			# Translators: The label shown for a deletion change 
			return _(u"deletion: {text}").format(text=text)
		else:
			# Translators: The general label shown for track changes 
			return _(u"track change: {text}").format(text=text)

def getCommentInfoFromPosition(position):
	"""
	Fetches information about the comment located at the given position in a word document.
	@param position: a TextInfo representing the span of the comment in the word document.
	@type L{TextInfo}
	@return: A dictionary containing keys of comment, author and date
	@rtype: dict
	"""
	val=position._rangeObj.getAttributeValue(UIAHandler.UIA_AnnotationObjectsAttributeId)
	if not val:
		return
	try:
		UIAElementArray=val.QueryInterface(UIAHandler.IUIAutomationElementArray)
	except COMError:
		return
	for index in range(UIAElementArray.length):
		UIAElement=UIAElementArray.getElement(index)
		UIAElement=UIAElement.buildUpdatedCache(UIAHandler.handler.baseCacheRequest)
		typeID = UIAElement.GetCurrentPropertyValue(UIAHandler.UIA_AnnotationAnnotationTypeIdPropertyId)
		# Use Annotation Type Comment if available
		if typeID == UIAHandler.AnnotationType_Comment:
			comment = UIAElement.GetCurrentPropertyValue(UIAHandler.UIA_NamePropertyId)
			author = UIAElement.GetCurrentPropertyValue(UIAHandler.UIA_AnnotationAuthorPropertyId)
			date = UIAElement.GetCurrentPropertyValue(UIAHandler.UIA_AnnotationDateTimePropertyId)
			return dict(comment=comment, author=author, date=date)
		else:
			obj = UIA(UIAElement=UIAElement)
			if (
				not obj.parent
				# Because the name of this object is language sensetive check if it has UIA Annotation Pattern
				or not obj.parent.UIAElement.getCurrentPropertyValue(
					UIAHandler.UIA_IsAnnotationPatternAvailablePropertyId
				)
			):
				continue
			comment = obj.makeTextInfo(textInfos.POSITION_ALL).text
			tempObj = obj.previous.previous
			authorObj = tempObj or obj.previous
			author = authorObj.name
			if not tempObj:
				return dict(comment=comment, author=author)
			dateObj = obj.previous
			date = dateObj.name
			return dict(comment=comment, author=author, date=date)


def getPresentableCommentInfoFromPosition(commentInfo):
	if "date" not in commentInfo:
		# Translators: The message reported for a comment in Microsoft Word
		return _("Comment: {comment} by {author}").format(**commentInfo)
	# Translators: The message reported for a comment in Microsoft Word
	return _("Comment: {comment} by {author} on {date}").format(**commentInfo)

class CommentUIATextInfoQuickNavItem(TextAttribUIATextInfoQuickNavItem):
	attribID=UIAHandler.UIA_AnnotationTypesAttributeId
	wantedAttribValues={UIAHandler.AnnotationType_Comment,}

	@property
	def label(self):
		commentInfo=getCommentInfoFromPosition(self.textInfo)
		return getPresentableCommentInfoFromPosition(commentInfo)

class WordDocumentTextInfo(UIATextInfo):

	def _get_locationText(self):
		point = self.pointAtStart
		# UIA has no good way yet to convert coordinates into user-configured distances such as inches or centimetres.
		# Nor can it give us specific distances from the edge of a page.
		# Therefore for now, get the screen coordinates, and if the word object model is available, use our legacy code to get the location text.
		om=self.obj.WinwordWindowObject
		if not om:
			return super(WordDocumentTextInfo,self).locationText
		try:
			r=om.rangeFromPoint(point.x,point.y)
		except (COMError,NameError):
			log.debugWarning("MS Word object model does not support rangeFromPoint")
			return super(WordDocumentTextInfo,self).locationText
		from  NVDAObjects.window.winword import WordDocumentTextInfo as WordObjectModelTextInfo
		i=WordObjectModelTextInfo(self.obj,None,_rangeObj=r)
		return i.locationText

	def _getTextWithFields_text(self,textRange,formatConfig,UIAFormatUnits=None):
		if UIAFormatUnits is None and self.UIAFormatUnits:
			# Word documents must always split by a unit the first time, as an entire text chunk can give valid annotation types 
			UIAFormatUnits=self.UIAFormatUnits
		return super(WordDocumentTextInfo,self)._getTextWithFields_text(textRange,formatConfig,UIAFormatUnits=UIAFormatUnits)

	def _get_controlFieldNVDAObjectClass(self):
		return WordDocumentNode

	def _getControlFieldForUIAObject(self, obj, isEmbedded=False, startOfNode=False, endOfNode=False):
		# Ignore strange editable text fields surrounding most inner fields (links, table cells etc) 
		automationID=obj.UIAElement.cachedAutomationID
		field = super(WordDocumentTextInfo, self)._getControlFieldForUIAObject(
			obj,
			isEmbedded=isEmbedded,
			startOfNode=startOfNode,
			endOfNode=endOfNode
		)
		if automationID.startswith('UIA_AutomationId_Word_Page_'):
			field['page-number']=automationID.rsplit('_',1)[-1]
		elif obj.UIAElement.cachedControlType==UIAHandler.UIA_GroupControlTypeId and obj.name:
			field['role']=controlTypes.Role.EMBEDDEDOBJECT
			field['alwaysReportName']=True
		elif obj.UIAElement.cachedControlType==UIAHandler.UIA_CustomControlTypeId and obj.name:
			# Include foot note and endnote identifiers
			field['content']=obj.name
			field['role']=controlTypes.Role.LINK
		if obj.role==controlTypes.Role.LIST or obj.role==controlTypes.Role.EDITABLETEXT:
			field['states'].add(controlTypes.State.READONLY)
			if obj.role==controlTypes.Role.LIST:
				# To stay compatible with the older MS Word implementation, don't expose lists in word documents as actual lists. This suppresses announcement of entering and exiting them.
				# Note that bullets and numbering are still announced of course.
				# Eventually we'll want to stop suppressing this, but for now this is more confusing than good (as in many cases announcing of new bullets when pressing enter causes exit and then enter to be spoken).
				field['role']=controlTypes.Role.EDITABLETEXT
		if obj.role==controlTypes.Role.GRAPHIC:
			# Label graphics with a description before name as name seems to be auto-generated (E.g. "rectangle")
			field['content'] = (
				field.pop('description', None)
				or obj.description
				or field.pop('name', None)
				or obj.name
			)
		return field

	def _getTextFromUIARange(self, textRange):
		t=super(WordDocumentTextInfo,self)._getTextFromUIARange(textRange)
		if t:
			# HTML emails expose a lot of vertical tab chars in their text
			# Really better as carage returns
			t=t.replace('\v','\r')
			# Remove end-of-row markers from the text - they are not useful
			t = t.replace(END_OF_ROW_MARK, '')
		return t

	def _isEndOfRow(self):
		""" Is this textInfo positioned on an end-of-row mark? """
		info=self.copy()
		info.expand(textInfos.UNIT_CHARACTER)
		return info._rangeObj.getText(-1)==u'\u0007'

	def move(self,unit,direction,endPoint=None):
		if endPoint is None:
			res=super(WordDocumentTextInfo,self).move(unit,direction)
			if res==0:
				return 0
			# Skip over end of Row marks
			while self._isEndOfRow():
				if self.move(unit,1 if direction>0 else -1)==0:
					break
			return res
		return super(WordDocumentTextInfo,self).move(unit,direction,endPoint)

	def expand(self,unit):
		super(WordDocumentTextInfo,self).expand(unit)
		# #7970: MS Word refuses to expand to line when on the final line and it is blank.
		# This among other things causes a newly inserted bullet not to be spoken or brailled.
		# Therefore work around this by detecting if the expand to line failed, and moving the end of the range to the end of the document manually.
		if  self.isCollapsed:
			if self.move(unit,1,endPoint="end")==0:
				docInfo=self.obj.makeTextInfo(textInfos.POSITION_ALL)
				self.setEndPoint(docInfo,"endToEnd")

	def getTextWithFields(self,formatConfig=None):
		fields = None
		# #11043: when a non-collapsed text range is positioned within a blank table cell
		# MS Word does not return the table  cell as an enclosing element,
		# Thus NVDa thinks the range is not inside the cell.
		# This can be detected by asking for the first 2 characters of the range's text,
		# Which will either be an empty string, or the single end-of-row mark.
		# Anything else means it is not on an empty table cell,
		# or the range really does span more than the cell itself.
		# If this situation is detected,
		# copy and collapse the range, and fetch the content from that instead,
		# As a collapsed range on an empty cell does correctly return the table cell as its first enclosing element.
		if not self.isCollapsed:
			rawText = self._rangeObj.GetText(2)
			if not rawText or rawText == END_OF_ROW_MARK:
				r = self.copy()
				r.end = r.start
				fields = super(WordDocumentTextInfo, r).getTextWithFields(formatConfig=formatConfig)
		if fields is None:
			fields = super().getTextWithFields(formatConfig=formatConfig)
		if len(fields)==0: 
			# Nothing to do... was probably a collapsed range.
			return fields
		# Sometimes embedded objects and graphics In MS Word can cause a controlStart then a controlEnd with no actual formatChange / text in the middle.
		# SpeakTextInfo always expects that the first lot of controlStarts will always contain some text.
		# Therefore ensure that the first lot of controlStarts does contain some text by inserting a blank formatChange and empty string in this case.
		for index in range(len(fields)):
			field=fields[index]
			if isinstance(field,textInfos.FieldCommand) and field.command=="controlStart":
				continue
			elif isinstance(field,textInfos.FieldCommand) and field.command=="controlEnd":
				formatChange=textInfos.FieldCommand("formatChange",textInfos.FormatField())
				fields.insert(index,formatChange)
				fields.insert(index+1,"")
			break
		##7971: Microsoft Word exposes list bullets as part of the actual text.
		# This then confuses NVDA's braille cursor routing as it expects that there is a one-to-one mapping between characters in the text string and   unit character moves.
		# Therefore, detect when at the start of a list, and strip the bullet from the text string, placing it in the text's formatField as line-prefix.
		listItemStarted=False
		lastFormatField=None
		for index in range(len(fields)):
			field=fields[index]
			if isinstance(field,textInfos.FieldCommand) and field.command=="controlStart":
				if field.field.get('role')==controlTypes.Role.LISTITEM and field.field.get('_startOfNode'):
					# We are in the start of a list item.
					listItemStarted=True
			elif isinstance(field,textInfos.FieldCommand) and field.command=="formatChange":
				# This is the most recent formatField we have seen.
				lastFormatField=field.field
			elif listItemStarted and isinstance(field,str):
				# This is the first text string within the list.
				# Remove the text up to the first space, and store it as line-prefix which NVDA will appropriately speak/braille as a bullet.
				try:
					spaceIndex=field.index(' ')
				except ValueError:
					log.debugWarning("No space found in this text string")
					break
				prefix=field[0:spaceIndex]
				fields[index]=field[spaceIndex+1:]
				lastFormatField['line-prefix']=prefix
				# Let speech know that line-prefix is safe to be spoken always, as it will only be exposed on the very first formatField on the list item.
				lastFormatField['line-prefix_speakAlways']=True
				break
			else:
				# Not a controlStart, formatChange or text string. Nothing to do.
				break
		# Fill in page number attributes where NVDA expects
		try:
			page=fields[0].field['page-number']
		except KeyError:
			page=None
		if page is not None:
			for field in fields:
				if isinstance(field,textInfos.FieldCommand) and isinstance(field.field,textInfos.FormatField):
					field.field['page-number']=page
		# MS Word can sometimes return a higher ancestor in its textRange's children.
		# E.g. a table inside a table header.
		# This does not cause a loop, but does cause information to be doubled
		# Detect these duplicates and remove them from the generated fields.
		seenStarts=set()
		pendingRemoves=[]
		index=0
		for index,field in enumerate(fields):
			if isinstance(field,textInfos.FieldCommand) and field.command=="controlStart":
				runtimeID=field.field['runtimeID']
				if not runtimeID:
					continue
				if runtimeID in seenStarts:
					pendingRemoves.append(field.field)
				else:
					seenStarts.add(runtimeID)
			elif seenStarts:
				seenStarts.clear()
		index=0
		while index<len(fields):
			field=fields[index]
			if isinstance(field,textInfos.FieldCommand) and any(x is field.field for x in pendingRemoves):
				del fields[index]
			else:
				index+=1
		return fields

class WordBrowseModeDocument(UIABrowseModeDocument):

	def shouldSetFocusToObj(self,obj):
		# Ignore strange editable text fields surrounding most inner fields (links, table cells etc) 
		if obj.role==controlTypes.Role.EDITABLETEXT and obj.UIAElement.cachedAutomationID.startswith('UIA_AutomationId_Word_Content'):
			return False
		return super(WordBrowseModeDocument,self).shouldSetFocusToObj(obj)

	def shouldPassThrough(self,obj,reason=None):
		# Ignore strange editable text fields surrounding most inner fields (links, table cells etc) 
		if obj.role==controlTypes.Role.EDITABLETEXT and obj.UIAElement.cachedAutomationID.startswith('UIA_AutomationId_Word_Content'):
			return False
		return super(WordBrowseModeDocument,self).shouldPassThrough(obj,reason=reason)

	def script_tab(self,gesture):
		oldBookmark=self.rootNVDAObject.makeTextInfo(textInfos.POSITION_SELECTION).bookmark
		gesture.send()
		noTimeout,newInfo=self.rootNVDAObject._hasCaretMoved(oldBookmark,timeout=1)
		if not newInfo:
			return
		info=self.makeTextInfo(textInfos.POSITION_SELECTION)
		if not info.isCollapsed:
			speech.speakTextInfo(info, reason=controlTypes.OutputReason.FOCUS)
	script_shiftTab=script_tab

	def _iterNodesByType(self,nodeType,direction="next",pos=None):
		if nodeType=="annotation":
			comments=UIATextAttributeQuicknavIterator(CommentUIATextInfoQuickNavItem,nodeType,self,pos,direction=direction)
			revisions=UIATextAttributeQuicknavIterator(RevisionUIATextInfoQuickNavItem,nodeType,self,pos,direction=direction)
			return browseMode.mergeQuickNavItemIterators([comments,revisions],direction)
		return super(WordBrowseModeDocument,self)._iterNodesByType(nodeType,direction=direction,pos=pos)

	ElementsListDialog=ElementsListDialog

class WordDocumentNode(UIA):
	TextInfo=WordDocumentTextInfo

	def _get_role(self):
		role=super(WordDocumentNode,self).role
		# Footnote / endnote elements currently have a role of unknown. Force them to editableText so that theyr text is presented correctly
		if role==controlTypes.Role.UNKNOWN:
			role=controlTypes.Role.EDITABLETEXT
		return role

class WordDocument(UIADocumentWithTableNavigation,WordDocumentNode,WordDocumentBase):
	treeInterceptorClass=WordBrowseModeDocument
	shouldCreateTreeInterceptor=False
	announceEntireNewLine=True

	# Microsoft Word duplicates the full title of the document on this control, which is redundant as it appears in the title of the app itself.
	name=u""

	def event_UIA_notification(self, activityId=None, **kwargs):
		# #10851: in recent Word 365 releases, UIA notification will cause NVDA to announce edit functions
		# such as "delete back word" when Control+Backspace is pressed.
		if activityId == "AccSN2":  # Delete activity ID
			return
		super(WordDocument, self).event_UIA_notification(**kwargs)

	@script(
		gesture="kb:NVDA+alt+c",
		# Translators: a description for a script that reports the comment at the caret.
		description=_("Reports the text of the comment where the System caret is located.")
	)
	def script_reportCurrentComment(self,gesture):
		caretInfo=self.makeTextInfo(textInfos.POSITION_CARET)
		commentInfo = getCommentInfoFromPosition(caretInfo)
		if commentInfo is not None:
			ui.message(getPresentableCommentInfoFromPosition(commentInfo))
		else:
			# Translators: a message when there is no comment to report in Microsoft Word
			ui.message(_("No comments"))
		return
