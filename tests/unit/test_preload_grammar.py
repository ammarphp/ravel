"""Native ReaderYODA/ReaderUtils phase controls; no native parser execution."""
from pathlib import Path
import pytest
from ravel.physics import rivet_preload as preload
from ravel.workflow.execution import file_hash
from test_rivet_preload import fixture


def rebind(task,path):
    task['centrality_preload']['sha256']=file_hash(path)
    task['centrality_preload']['origin']['sha256']=file_hash(path)


@pytest.mark.parametrize('annotation', [
    '"Path": /RAW/Unexpected', "'Path': /RAW/Unexpected", 'Path: /RAW/Unexpected',
    '"\\u0050ath": /RAW/Unexpected', '<<: *base', '? Path',
    'Type: Other', 'MaskedBins: 1', 'Title: |', ' Path: /Calibration/V0M'])
def test_native_annotation_identity_and_closed_yaml_domain(tmp_path,annotation):
    task,cc,path=fixture(tmp_path)
    path.write_text(path.read_text().replace('---\n',annotation+'\n---\n',1));rebind(task,path)
    with pytest.raises(ValueError,match='annotation|Path|masked'):
        preload.inspect(task,tmp_path,admitted_source_files=[cc])


@pytest.mark.parametrize('mask',[' MaskedBins: [1]','\tMaskedBins: [1]','MaskedBins: [1]','  MaskedBins: []'])
def test_native_trimmed_mask_directives_never_pass_unmasked_domain(tmp_path,mask):
    task,cc,path=fixture(tmp_path)
    path.write_text(path.read_text().replace('---\n','---\n'+mask+'\n',1));rebind(task,path)
    with pytest.raises(ValueError,match='masked'):
        preload.inspect(task,tmp_path,admitted_source_files=[cc])
    destination=tmp_path/'must-not-publish.yoda'
    with pytest.raises(ValueError,match='masked'):
        preload.prepare(path,expected_sha256=file_hash(path),object_path='/Calibration/V0M',output_path=destination)
    assert not destination.exists()


@pytest.mark.parametrize('mutation',[
    lambda s:s.replace('---\n',''),lambda s:s.replace('---\n','---\n---\n'),
    lambda s:s.replace('---\nEdges(A1): [0,1,3]\n','Edges(A1): [0,1,3]\n---\n'),
    lambda s:s.replace('Edges(A1):',' Edges(A1):'),
    lambda s:s.replace('# value','# END BAD\n# value')])
def test_native_phase_directive_and_context_marker_refusals(tmp_path,mutation):
    task,cc,path=fixture(tmp_path);path.write_text(mutation(path.read_text()));rebind(task,path)
    with pytest.raises(ValueError):preload.inspect(task,tmp_path,admitted_source_files=[cc])


def test_standard_writer_annotations_and_byte_preservation(tmp_path):
    task,cc,path=fixture(tmp_path)
    text=path.read_text().replace('---\n','Title: generated calibration\nType: Estimate1D\nScaledBy: 1.25e-3\n---\n',1)
    path.write_text(text);rebind(task,path)
    before=path.read_bytes();result=preload.inspect(task,tmp_path,admitted_source_files=[cc])
    assert result['object_path']=='/Calibration/V0M' and path.read_bytes()==before
    output=tmp_path/'subset.yoda'
    preload.prepare(path,expected_sha256=file_hash(path),object_path='/Calibration/V0M',output_path=output)
    assert output.read_bytes()==before


def test_native_writer_padding_tabs_are_preserved(tmp_path):
    task,cc,path=fixture(tmp_path)
    text=path.read_text().replace('# value totalDn totalUp','# value      \terrDn(1)\terrUp(1)\t').replace('ErrorLabels: [""]','ErrorLabels: ["stats"]')
    text=text.replace(' -0.1 0.1',' \t-0.1\t0.1 \t')
    path.write_text(text);rebind(task,path)
    result=preload.inspect(task,tmp_path,admitted_source_files=[cc])
    assert result['native_object']['columns']==['value','errDn(1)','errUp(1)']
    assert result['native_object']['bins'][1]['value_token']=='1'
    assert path.read_text()==text
