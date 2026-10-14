"""Reversible source instrumentation selected by a supplied descriptor.

This edits source bytes only. Native compilation, execution and observer
noninterference use the existing governed build and event-processing workflow.
"""
import hashlib
from .truth_reco_response import ResponseInputError


def instrument(raw,descriptor=None):
    if not isinstance(descriptor,dict) or not {'schema_version','source_sha256','edits'}<=set(descriptor):
        raise ResponseInputError('supplied instrumentation descriptor required','missing_input')
    if set(descriptor)!={'schema_version','source_sha256','edits'} or type(descriptor['schema_version']) is not int or descriptor['schema_version']!=1:
        raise ResponseInputError('closed instrumentation descriptor/v1 required')
    if type(raw) is not bytes or hashlib.sha256(raw).hexdigest()!=descriptor['source_sha256']:
        raise ResponseInputError('source bytes differ from supplied instrumentation pin')
    edits=descriptor['edits']
    if not isinstance(edits,list) or not 1<=len(edits)<=1024:raise ResponseInputError('bounded complete edit ledger required')
    source=raw.decode('utf-8');applied=[]
    for row in edits:
        if not isinstance(row,dict) or set(row)!={'old','new','count'} or not isinstance(row['old'],str) or not row['old'] or not isinstance(row['new'],str) or not row['new'] or row['old']==row['new'] or type(row['count']) is not int or row['count']<1:
            raise ResponseInputError('explicit reversible source edit required')
        if source.count(row['old'])!=row['count']:raise ResponseInputError('source anchor count changed')
        source=source.replace(row['old'],row['new']);applied.append(dict(row))
    reconstructed=source
    for row in reversed(applied):
        if reconstructed.count(row['new'])!=row['count']:raise ResponseInputError('nonunique inverse edit')
        reconstructed=reconstructed.replace(row['new'],row['old'])
    if reconstructed.encode('utf-8')!=raw:raise ResponseInputError('full source inverse differs')
    return source.encode('utf-8'),applied
