"""AUTHORED/UNRUN: actual HTMLParser and ordinary located-source routes."""
import hashlib
from ravel.workflow import literature_context as lc
from test_literature_context import document,request,refuse_real_network


def test_actual_multiline_unicode_void_and_selfclosing_locations(tmp_path):
    text='π pre\n<article>\n<h1>μ &amp; Ω</h1>\n<p>α\nβ</p>\n<img src="γ.png">\n<section/>\n<math>x</math>\n</article>\n尾'
    parser=lc._HTML(text)
    rows,errors=parser.forest()  # real inherited feed/close/updatepos
    fragments=['<article>\n<h1>μ &amp; Ω</h1>\n<p>α\nβ</p>\n<img src="γ.png">\n<section/>\n<math>x</math>\n</article>',
               '<h1>μ &amp; Ω</h1>','<p>α\nβ</p>','<img src="γ.png">','<section/>','<math>x</math>']
    assert errors==[] and len(rows)==6
    assert [row['tag'] for row in rows]==['article','h1','p','img','section','math']
    assert [row['parent_index'] for row in rows]==[None,0,0,0,0,0]
    assert [(r['start'],r['end']) for r in rows]==[(text.index(f),text.index(f)+len(f)) for f in fragments]
    assert type(parser.offset) is int and parser.getpos()==(text.count('\n')+1,1)
    base=tmp_path.resolve();doc=document(base,'html',text,'html')
    result=lc.prepare(request(base,[doc]),base/'located',base_dir=base)
    assert lc.consume(result['product'],base_dir=base)==result
    units=result['context']['units'];parents={u['parent'] for u in units}
    leaves=sorted((u['start'],u['end'],u['text']) for u in units if u['id'] not in parents)
    assert ''.join(piece for _,_,piece in leaves)==text
    for fragment in fragments:
        selected=[u for u in units if u['text']==fragment]
        assert len(selected)==1
        u=selected[0];start=text.index(fragment)
        assert (u['start'],u['end'])==(start,start+len(fragment))
        assert (u['byte_start'],u['byte_end'])==(len(text[:start].encode()),len(text[:start+len(fragment)].encode()))
        assert u['line_start']==text[:start].count('\n')+1
        assert u['excerpt_sha256']==hashlib.sha256(fragment.encode()).hexdigest()
    assert not any(result['context']['claims'].values())


def test_actual_multiline_unicode_unmatched_and_unclosed_offsets(tmp_path):
    text="μ\n</table>\n<figure><img src='π.png'/><figcaption>Γ</figcaption></figure>\n<section>unfinished"
    parser=lc._HTML(text);rows,errors=parser.forest()
    assert errors==[
        {'offset':text.index('</table>'),'reason':'unmatched structural HTML end tag','tag':'table'},
        {'offset':text.index('<section>'),'reason':'unclosed structural HTML element','tag':'section'}]
    assert [r['tag'] for r in rows]==['figure','img','figcaption','section']
    assert rows[1]['parent_index']==0 and rows[2]['parent_index']==0 and rows[3]['parent_index'] is None
    assert rows[1]['end']==text.index("<img src='π.png'/>")+len("<img src='π.png'/>")
    assert rows[0]['end']==text.index('</figure>')+len('</figure>') and rows[3]['end']==len(text)
    assert type(parser.offset) is int
    base=tmp_path.resolve();doc=document(base,'html',text,'html')
    result=lc.prepare(request(base,[doc]),base/'located',base_dir=base)
    assert lc.consume(result['product'],base_dir=base)==result
    actual=[r for r in result['context']['missing_and_unresolved'] if r['kind']=='parse']
    assert [(r['offset'],r['reason'],r['tag']) for r in actual]==[(e['offset'],e['reason'],e['tag']) for e in errors]
    assert result['context']['extraction_status']=='partial_or_unresolved'
    assert result['context']['units'][0]['text']==text
    assert not any(result['context']['claims'].values())
