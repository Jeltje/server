"""
Tests related to exceptions
"""

from __future__ import division
from __future__ import print_function
from __future__ import unicode_literals

import unittest
import inspect

import ga4gh.exceptions as exceptions
import ga4gh.frontend as frontend
import ga4gh.protocol as protocol


class TestExceptionHandler(unittest.TestCase):
    """
    Test that caught exceptions are handled correctly
    """
    class UnknownException(Exception):
        pass

    def getGa4ghException(self, data):
        return protocol.GAException.fromJsonString(data)

    def testObjectNotFoundException(self):
        exception = exceptions.ObjectNotFoundException()
        response = frontend.handleException(exception)
        self.assertEquals(response.status_code, 404)

    def testCallSetNotInVariantSetException(self):
        exception = exceptions.CallSetNotInVariantSetException(
            'csId', 'vsId')
        response = frontend.handleException(exception)
        self.assertEquals(response.status_code, 404)
        gaException = self.getGa4ghException(response.data)
        self.assertGreater(len(gaException.message), 0)

    def testUnknownExceptionBecomesServerError(self):
        exception = self.UnknownException()
        response = frontend.handleException(exception)
        self.assertEquals(response.status_code, 500)
        gaException = self.getGa4ghException(response.data)
        self.assertEquals(gaException.message, exceptions.ServerError.message)

    def testNotImplementedException(self):
        message = "A string unlikely to occur at random."
        exception = exceptions.NotImplementedException(message)
        response = frontend.handleException(exception)
        self.assertEquals(response.status_code, 501)
        gaException = self.getGa4ghException(response.data)
        self.assertEquals(gaException.message, message)


def isClassAndExceptionSubclass(class_):
    return inspect.isclass(class_) and issubclass(class_, Exception)


class TestExceptionConsistency(unittest.TestCase):
    """
    Ensure invariants of exceptions:
    - every exception has a non-None error code
    - every exception has a unique error code
    - every exception can be instantiated successfully
    """
    def _getExceptionClasses(self):
        classes = inspect.getmembers(
            exceptions, isClassAndExceptionSubclass)
        return [class_ for _, class_ in classes]

    def testCodeInvariants(self):
        codes = set()
        for class_ in self._getExceptionClasses():
            code = class_.getErrorCode()
            self.assertNotIn(code, codes)
            codes.add(code)
            self.assertIsNotNone(code)

    def testInstantiation(self):
        for class_ in self._getExceptionClasses():
            # some exceptions are becoming too complicated to instantiate
            # like the rest of the exceptions; just do them manually
            if class_ == exceptions.RequestValidationFailureException:
                wrongString = "thisIsWrong"
                objClass = protocol.SearchReadsRequest
                obj = objClass()
                obj.start = wrongString
                jsonDict = obj.toJsonDict()
                args = (jsonDict, objClass)
            elif class_ == exceptions.ResponseValidationFailureException:
                objClass = protocol.SearchReadsResponse
                obj = objClass()
                obj.alignments = [protocol.ReadAlignment()]
                obj.alignments[0].alignment = protocol.LinearAlignment()
                obj.alignments[0].alignment.mappingQuality = wrongString
                jsonDict = obj.toJsonDict()
                args = (jsonDict, objClass)
            else:
                numInitArgs = len(inspect.getargspec(
                    class_.__init__).args) - 1
                args = ['arg' for _ in range(numInitArgs)]
            instance = class_(*args)
            self.assertIsInstance(instance, exceptions.BaseServerException)
            message = instance.getMessage()
            self.assertIsInstance(message, basestring)
            self.assertGreater(len(message), 0)
            self.assertEqual(instance.getErrorCode(), class_.getErrorCode())

    def testValidationFailureExceptionMessages(self):
        # RequestValidationFailureException
        wrongString = "thisIsWrong"
        objClass = protocol.SearchReadsRequest
        obj = objClass()
        obj.start = wrongString
        jsonDict = obj.toJsonDict()
        instance = exceptions.RequestValidationFailureException(
            jsonDict, objClass)
        self.assertIn(
            "invalid fields: {u'start': u'thisIsWrong'}",
            instance.message)
        self.assertEqual(instance.message.count(wrongString), 2)

        # ResponseValidationFailureException
        objClass = protocol.SearchReadsResponse
        obj = objClass()
        obj.alignments = [protocol.ReadAlignment()]
        obj.alignments[0].alignment = protocol.LinearAlignment()
        obj.alignments[0].alignment.mappingQuality = wrongString
        jsonDict = obj.toJsonDict()
        instance = exceptions.ResponseValidationFailureException(
            jsonDict, objClass)
        self.assertIn("Invalid fields", instance.message)
        self.assertEqual(instance.message.count(wrongString), 2)
