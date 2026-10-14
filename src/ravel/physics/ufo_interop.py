"""Explicit literal UFOError raise interoperability; no UFO import/evaluation.

This is the narrow observed FeynRules2.3.49 Python2 raise form. It implements
the same raise-to-exception-constructor step as MG5's model converter without
its unrelated card-writer replacement or import changes. It is not a general
Python2 converter, nor a model validation operation.
"""
import ast
import io
from pathlib import Path
import hashlib
import stat
import tokenize

from ravel.physics import model_tool_bridge as custody

POLICY='feynrules-2.3.49-literal-UFOError-raise-v1'

def source_tree(root):
    """Closed ordinary member inventory, including empty files; no exclusions."""
    root=custody._regular(root,Path.cwd(),directory=True);rows={};size=0
    for file in sorted(root.rglob('*')):
        if file.is_symlink() or not(file.is_file() or file.is_dir()):
            raise ValueError('only regular source members and ordinary directories are admitted')
        if file.is_file():
            rows[file.relative_to(root).as_posix()]=custody._hash(file);size+=file.stat().st_size
    if not 1<=len(rows)<=20000 or size>512*1024**2:
        raise ValueError('bounded complete UFO member inventory required')
    return {'schema_version':1,'files':rows}

def convert_text(text):
    """Rewrite only tokenized raise UFOError, literal-string statements."""
    lines=text.splitlines(keepends=True);offsets=[0]
    for line in lines:offsets.append(offsets[-1]+len(line))
    def offset(position):return offsets[position[0]-1]+position[1]
    tokens=list(tokenize.generate_tokens(io.StringIO(text).readline))
    edits=[]
    for i,token in enumerate(tokens):
        if token.type!=tokenize.NAME or token.string!='raise':continue
        following=tokens[i+1:i+5]
        if len(following)!=4:continue
        exception,comma,literal,end=following
        if (exception.type==tokenize.NAME and exception.string=='UFOError'
                and comma.type==tokenize.OP and comma.string==','
                and literal.type==tokenize.STRING
                and end.type in (tokenize.NEWLINE,tokenize.COMMENT,tokenize.ENDMARKER)):
            value=ast.literal_eval(literal.string)
            if not isinstance(value,str):raise ValueError('only literal string UFOError messages are admitted')
            edits.append((offset(exception.end),offset(literal.end),'('+literal.string+')',
                {'line':token.start[0],'exception':'UFOError','message':value}))
    converted=text
    for start,end,replacement,_ in reversed(edits):converted=converted[:start]+replacement+converted[end:]
    ast.parse(converted)
    return converted,[item[3] for item in edits]

def convert_tree(raw,output,policy):
    """Preserve raw tree, copy all members/modes, and journal exact text deltas."""
    if policy!=POLICY:raise ValueError('explicit supported UFO compatibility policy required')
    raw=custody._regular(raw,Path.cwd(),directory=True);output=Path(output).absolute()
    if output.resolve()!=output or output.exists() or any(p.is_symlink() for p in (output,*output.parents)):
        raise ValueError('fresh canonical converted UFO directory required')
    if output.is_relative_to(raw):raise ValueError('converted UFO must remain separate from raw tree')
    before=source_tree(raw);modes={n:stat.S_IMODE((raw/n).stat().st_mode) for n in before['files']}
    output.mkdir(parents=True);deltas={}
    for name,fact in before['files'].items():
        source=custody._regular(name,raw);destination=output/name;destination.parent.mkdir(parents=True,exist_ok=True)
        data=source.read_bytes();edits=[]
        if hashlib.sha256(data).hexdigest()!=fact:raise ValueError('raw UFO member changed before conversion read')
        if source.suffix=='.py':
            converted,edits=convert_text(data.decode('utf-8'))
            if edits:
                tree=ast.parse(converted)
                classes=[node for node in ast.walk(tree) if isinstance(node,ast.ClassDef) and node.name=='UFOError']
                if (name!='object_library.py' or len(classes)!=1 or classes[0] not in tree.body
                        or classes[0].decorator_list or classes[0].keywords or len(classes[0].bases)!=1
                        or not isinstance(classes[0].bases[0],ast.Name) or classes[0].bases[0].id!='Exception'
                        or any(not(isinstance(node,ast.Pass) or isinstance(node,ast.Expr)
                            and isinstance(node.value,ast.Constant) and isinstance(node.value.value,str)) for node in classes[0].body)
                        or any(isinstance(node,ast.Name) and node.id=='UFOError' and isinstance(node.ctx,(ast.Store,ast.Del))
                            or isinstance(node,ast.arg) and node.arg=='UFOError'
                            or isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef)) and node.name=='UFOError'
                            or isinstance(node,ast.alias) and (node.asname or node.name.split('.')[0])=='UFOError'
                            or isinstance(node,ast.ImportFrom) and any(alias.name=='*' for alias in node.names)
                            or isinstance(node,ast.ExceptHandler) and node.name=='UFOError'
                            or isinstance(node,(ast.MatchAs,ast.MatchStar)) and node.name=='UFOError'
                            or isinstance(node,ast.MatchMapping) and node.rest=='UFOError'
                            or isinstance(node,(ast.Global,ast.Nonlocal)) and 'UFOError' in node.names
                            or type(node).__name__ in ('TypeVar','ParamSpec','TypeVarTuple') and node.name=='UFOError'
                            for node in ast.walk(tree))):
                    raise ValueError('observed canonical pass-only UFOError(Exception) definition required')
            data=converted.encode('utf-8')
        with destination.open('xb') as handle:handle.write(data)
        destination.chmod(modes[name])
        if custody._hash(destination)!=custody._hash(source):
            deltas[name]={'raw_sha256':custody._hash(source),'converted_sha256':custody._hash(destination),
                'literal_raise_edits':edits}
    after=source_tree(raw);converted=source_tree(output)
    if after!=before or modes!={n:stat.S_IMODE((raw/n).stat().st_mode) for n in before['files']}:
        raise ValueError('raw UFO source changed during conversion')
    if set(converted['files'])!=set(before['files']) or any(stat.S_IMODE((output/n).stat().st_mode)!=modes[n] for n in modes):
        raise ValueError('converted UFO member/mode census differs')
    return {'schema_version':1,'policy':policy,'raw_tree':before,'converted_tree':converted,
        'source_modes':modes,'changed_files':deltas,'raw_tree_unchanged':True,'model_imported':False,
        'scope':'Literal UFOError raise syntax only; no imports/card-writer/parameter/coupling/vertex changes or model validity inferred.'}
