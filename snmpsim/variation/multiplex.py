#
# This file is part of snmpsim software.
#
# Copyright (c) 2010-2019, Ilya Etingof <etingof@gmail.com>
# License: https://www.pysnmp.com/snmpsim/license.html
#
# Managed value variation module: simulate a live Agent using
# a series of snapshots.
#
import bisect
import os
import time

from pyasn1.compat.octets import str2octs
from pysnmp.proto import rfc1902

from snmpsim import confdir
from snmpsim import error
from snmpsim import log
from snmpsim.record import dump
from snmpsim.record import mvc
from snmpsim.record import sap
from snmpsim.record import snmprec
from snmpsim.record import walk
from snmpsim.record.search.database import RecordIndex
from snmpsim.record.search.file import get_record
from snmpsim.record.search.file import search_record_by_oid
from snmpsim.utils import split

# data file types and parsers
RECORD_SET = {
    dump.DumpRecord.ext: dump.DumpRecord(),
    mvc.MvcRecord.ext: mvc.MvcRecord(),
    sap.SapRecord.ext: sap.SapRecord(),
    walk.WalkRecord.ext: walk.WalkRecord(),
    snmprec.SnmprecRecord.ext: snmprec.SnmprecRecord(),
    snmprec.CompressedSnmprecRecord.ext: snmprec.CompressedSnmprecRecord()
}


def init(**context):

    if context['options']:
        for x in split(context['options'], ','):
            k, v = split(x, ':')
            if k == 'addon':
                if k in moduleContext:
                    moduleContext[k].append(v)

                else:
                    moduleContext[k] = [v]

            else:
                moduleContext[k] = v

    if context['mode'] == 'variating':
        moduleContext['booted'] = time.time()

    elif context['mode'] == 'recording':
        if 'dir' not in moduleContext:
            raise error.SnmpsimError(
                'SNMP snapshots directory not specified')

        if not os.path.exists(moduleContext['dir']):
            log.info('multiplex: creating '
                    '%s...' % moduleContext['dir'])

            os.makedirs(moduleContext['dir'])

        if 'iterations' in moduleContext:
            moduleContext['iterations'] = max(
                0, int(moduleContext['iterations']) - 1)

        if 'period' in moduleContext:
            moduleContext['period'] = float(moduleContext['period'])

        else:
            moduleContext['period'] = 10.0

    moduleContext['ready'] = True


def variate(oid, tag, value, **context):

    if 'settings' not in recordContext:
        recordContext['settings'] = dict(
            [split(x, '=') for x in split(value, ',')])

        if 'dir' not in recordContext['settings']:
            log.info('multiplex: snapshot directory not specified')
            return context['origOid'], tag, context['errorStatus']

        recordContext['settings']['dir'] = recordContext[
            'settings']['dir'].replace('/', os.path.sep)

        if recordContext['settings']['dir'][0] != os.path.sep:
            for x in confdir.data:
                d = os.path.join(x, recordContext['settings']['dir'])
                if os.path.exists(d):
                    break

            else:
                log.info('multiplex: directory %s not '
                        'found' % recordContext['settings']['dir'])
                return context['origOid'], tag, context['errorStatus']

        else:
            d = recordContext['settings']['dir']

        recordContext['dirmap'] = {}
        recordContext['parsermap'] = {}

        for fl in os.listdir(d):
            for ext in RECORD_SET:
                if not fl.endswith(ext):
                    continue
                ident = int(os.path.basename(fl)[:-len(ext) - 1])
                datafile = os.path.join(d, fl)
                recordContext['dirmap'][ident] = datafile
                recordContext['parsermap'][datafile] = RECORD_SET[ext]

        recordContext['keys'] = list(recordContext['dirmap'])

        recordContext['bounds'] = (
            min(recordContext['keys']), max(recordContext['keys']))

        if 'period' in recordContext['settings']:
            recordContext['settings']['period'] = float(
                recordContext['settings']['period'])

        else:
            recordContext['settings']['period'] = 60.0

        if 'wrap' in recordContext['settings']:
            recordContext['settings']['wrap'] = bool(
                recordContext['settings']['wrap'])

        else:
            recordContext['settings']['wrap'] = False

        if 'control' in recordContext['settings']:
            recordContext['settings']['control'] = rfc1902.ObjectName(
                recordContext['settings']['control'])

            log.info(
                'multiplex: using control OID %s for subtree %s, '
                'time-based multiplexing '
                'disabled' % (recordContext['settings']['control'], oid))

        recordContext['ready'] = True

    if 'ready' not in recordContext:
        return context['origOid'], tag, context['errorStatus']

    if oid not in moduleContext:
        moduleContext[oid] = {}

    if context['setFlag']:
        if 'control' in (
                recordContext['settings'] and
                recordContext['settings']['control'] == context['origOid']):

            fileno = int(context['origValue'])
            if fileno >= len(recordContext['keys']):
                log.info('multiplex: .snmprec file number %s over limit of'
                        ' %s' % (fileno, len(recordContext['keys'])))

                return context['origOid'], tag, context['errorStatus']

            moduleContext[oid]['fileno'] = fileno

            log.info(
                'multiplex: switched to file #%s '
                '(%s)' % (recordContext['keys'][fileno],
                          recordContext['dirmap'][recordContext['keys'][fileno]]))

            return context['origOid'], tag, context['origValue']

        else:
            return context['origOid'], tag, context['errorStatus']

    if 'control' in recordContext['settings']:
        if 'fileno' not in moduleContext[oid]:
            moduleContext[oid]['fileno'] = 0

        if (not context['nextFlag'] and
                recordContext['settings']['control'] == context['origOid']):

            val = rfc1902.Integer32(moduleContext[oid]['fileno'])

            return context['origOid'], tag, val

    else:
        period = recordContext['settings']['period']

        uptime = time.time() - moduleContext['booted']
        timeslot = uptime % (period * len(recordContext['dirmap']))

        fileslot = int(timeslot / period) + recordContext['bounds'][0]

        fileno = bisect.bisect(recordContext['keys'], fileslot) - 1

        if ('fileno' not in moduleContext[oid] or
                moduleContext[oid]['fileno'] < fileno or
                recordContext['settings']['wrap']):
            moduleContext[oid]['fileno'] = fileno

    datafile = recordContext['dirmap'][
        recordContext['keys'][moduleContext[oid]['fileno']]]

    parser = recordContext['parsermap'][datafile]

    if ('datafile' not in moduleContext[oid] or
            moduleContext[oid]['datafile'] != datafile):

        if 'datafileobj' in moduleContext[oid]:
            moduleContext[oid]['datafileobj'].close()

        recordIndex = RecordIndex(datafile, parser).create()

        moduleContext[oid]['datafileobj'] = recordIndex

        moduleContext[oid]['datafile'] = datafile

        log.info(
            'multiplex: switching to data file %s for '
            '%s' % (datafile, context['origOid']))

    text, db = moduleContext[oid]['datafileobj'].get_handles()

    textOid = str(rfc1902.OctetString(
        '.'.join(['%s' % x for x in context['origOid']])))

    try:
        line = moduleContext[oid]['datafileobj'].lookup(textOid)

    except KeyError:
        offset = search_record_by_oid(context['origOid'], text, parser)
        exactMatch = False

    else:
        offset, subtreeFlag, prevOffset = line.split(str2octs(','))
        exactMatch = True

    text.seek(int(offset))

    line, _, _ = get_record(text)  # matched line

    if context['nextFlag']:
        if exactMatch:
            line, _, _ = get_record(text)

    else:
        if not exactMatch:
            return context['origOid'], tag, context['errorStatus']

    if not line:
        return context['origOid'], tag, context['errorStatus']

    try:
        oid, value = parser.evaluate(line)

    except error.SnmpsimError:
        oid, value = context['origOid'], context['errorStatus']

    return oid, tag, value


def record(oid, tag, value, **context):
    if 'ready' not in moduleContext:
        raise error.SnmpsimError('module not initialized')

    if 'started' not in moduleContext:
        moduleContext['started'] = time.time()

    if context['stopFlag']:
        if 'file' in moduleContext:
            moduleContext['file'].close()
            del moduleContext['file']

        else:
            moduleContext['filenum'] = 0

        if 'iterations' in moduleContext and moduleContext['iterations']:
            log.info('multiplex: %s iterations '
                    'remaining' % moduleContext['iterations'])

            moduleContext['started'] = time.time()
            moduleContext['iterations'] -= 1
            moduleContext['filenum'] += 1

            wait = max(0, moduleContext['period'] - (time.time() - moduleContext['started']))

            raise error.MoreDataNotification(period=wait)

        else:
            raise error.NoDataNotification()

    if 'file' not in moduleContext:
        if 'filenum' not in moduleContext:
            moduleContext['filenum'] = 0

        dstRecordType = moduleContext.get('recordtype', 'snmprec')

        ext = os.path.extsep + RECORD_SET[dstRecordType].ext

        snmprecFile = '%.5d%s%s' % (
            moduleContext['filenum'], os.path.extsep, ext)

        snmprecfile = os.path.join(moduleContext['dir'], snmprecFile)

        moduleContext['parser'] = RECORD_SET[dstRecordType]
        moduleContext['file'] = moduleContext['parser'].open(snmprecfile, 'wb')

        log.info('multiplex: writing into %s file...' % snmprecfile)

    record = moduleContext['parser'].format(
        context['origOid'], context['origValue'])

    moduleContext['file'].write(record)

    if not context['total']:
        settings = {
            'dir': moduleContext['dir'].replace(os.path.sep, '/')
        }

        if 'period' in moduleContext:
            settings['period'] = '%.2f' % float(moduleContext['period'])

        if 'addon' in moduleContext:
            settings.update(
                dict([split(x, '=') for x in moduleContext['addon']])
            )

        value = ','.join(['%s=%s' % (k, v) for k, v in settings.items()])

        return str(context['startOID']), ':multiplex', value

    else:
        raise error.NoDataNotification()


def shutdown(**context):
    pass
