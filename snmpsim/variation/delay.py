#
# This file is part of snmpsim software.
#
# Copyright (c) 2010-2019, Ilya Etingof <etingof@gmail.com>
# License: https://www.pysnmp.com/snmpsim/license.html
#
import random
import time

from snmpsim import error
from snmpsim import log
from snmpsim.grammar.snmprec import SnmprecGrammar
from snmpsim.record.snmprec import SnmprecRecord
from snmpsim.utils import split


def init(**context):
    random.seed()


def variate(oid, tag, value, **context):
    if not context['nextFlag'] and not context['exactMatch']:
        return context['origOid'], tag, context['errorStatus']

    if 'settings' not in recordContext:
        recordContext['settings'] = dict(
            [split(x, '=') for x in split(value, ',')])

        if 'hexvalue' in recordContext['settings']:
            recordContext['settings']['value'] = [
                int(recordContext['settings']['hexvalue'][x:x + 2], 16)
                for x in range(0, len(recordContext['settings']['hexvalue']), 2)]

        if 'wait' in recordContext['settings']:
            recordContext['settings']['wait'] = float(
                recordContext['settings']['wait'])

        else:
            recordContext['settings']['wait'] = 500.0

        if 'deviation' in recordContext['settings']:
            recordContext['settings']['deviation'] = float(
                recordContext['settings']['deviation'])

        else:
            recordContext['settings']['deviation'] = 0.0

        if 'vlist' in recordContext['settings']:

            vlist = {}

            recordContext['settings']['vlist'] = split(
                recordContext['settings']['vlist'], ':')

            while recordContext['settings']['vlist']:
                o, v, d = recordContext['settings']['vlist'][:3]

                recordContext['settings']['vlist'] = recordContext['settings']['vlist'][3:]

                d = int(d)

                type_tag, _ = SnmprecRecord.unpack_tag(tag)

                v = SnmprecGrammar.TAG_MAP[type_tag](v)

                if o not in vlist:
                    vlist[o] = {}

                if o == 'eq':
                    vlist[o][v] = d

                elif o in ('lt', 'gt'):
                    vlist[o] = v, d

                else:
                    log.info('delay: bad vlist syntax: '
                            '%s' % recordContext['settings']['vlist'])

            recordContext['settings']['vlist'] = vlist

        if 'tlist' in recordContext['settings']:
            tlist = {}

            recordContext['settings']['tlist'] = split(
                recordContext['settings']['tlist'], ':')

            while recordContext['settings']['tlist']:
                o, v, d = recordContext['settings']['tlist'][:3]

                recordContext['settings']['tlist'] = recordContext['settings']['tlist'][3:]

                v = int(v)
                d = int(d)

                if o not in tlist:
                    tlist[o] = {}

                if o == 'eq':
                    tlist[o][v] = d

                elif o in ('lt', 'gt'):
                    tlist[o] = v, d

                else:
                    log.info('delay: bad tlist syntax: '
                            '%s' % recordContext['settings']['tlist'])

            recordContext['settings']['tlist'] = tlist

    if context['setFlag'] and 'vlist' in recordContext['settings']:
        if ('eq' in recordContext['settings']['vlist'] and
                    context['origValue'] in recordContext['settings']['vlist']['eq']):
            delay = recordContext['settings']['vlist']['eq'][context['origValue']]

        elif ('lt' in recordContext['settings']['vlist'] and
                context['origValue'] < recordContext['settings']['vlist']['lt'][0]):
            delay = recordContext['settings']['vlist']['lt'][1]

        elif ('gt' in recordContext['settings']['vlist'] and
                context['origValue'] > recordContext['settings']['vlist']['gt'][0]):
            delay = recordContext['settings']['vlist']['gt'][1]

        else:
            delay = recordContext['settings']['wait']

    elif 'tlist' in recordContext['settings']:
        now = int(time.time())
        if ('eq' in recordContext['settings']['tlist'] and
                now == recordContext['settings']['tlist']['eq']):
            delay = recordContext['settings']['tlist']['eq'][now]

        elif ('lt' in recordContext['settings']['tlist'] and
                now < recordContext['settings']['tlist']['lt'][0]):
            delay = recordContext['settings']['tlist']['lt'][1]

        elif ('gt' in recordContext['settings']['tlist'] and
                now > recordContext['settings']['tlist']['gt'][0]):
            delay = recordContext['settings']['tlist']['gt'][1]

        else:
            delay = recordContext['settings']['wait']

    else:
        delay = recordContext['settings']['wait']

    if recordContext['settings']['deviation']:
        delay += random.randrange(
            -recordContext['settings']['deviation'],
            recordContext['settings']['deviation'])

    if delay < 0:
        delay = 0

    elif delay > 99999:
        log.info('delay: dropping response for %s' % oid)
        raise error.NoDataNotification()

    log.info('delay: waiting %d milliseconds for %s' % (delay, oid))

    time.sleep(delay / 1000)  # ms

    if context['setFlag'] or 'value' not in recordContext['settings']:
        return oid, tag, context['origValue']

    else:
        return oid, tag, recordContext['settings']['value']


def record(oid, tag, value, **context):
    if context['stopFlag']:
        raise error.NoDataNotification()

    tag += ':delay'
    if 'hexvalue' in context:
        text_value = 'hexvalue=' + context['hexvalue']

    else:
        text_value = 'value=' + value

    text_value += ',wait=%d' % int((time.time() - context['reqTime']) * 1000)  # ms

    if 'options' in context:
        text_value += ',' + context['options']

    return oid, tag, text_value


def shutdown(**context):
    pass
