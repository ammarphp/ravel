"""Public parser/dispatch source controls; no tool/plan/approval/run execution."""
from pathlib import Path
from importlib import import_module
import re
import types
import pytest
from ravel import cli

@pytest.mark.parametrize('command,tail',[
 ('plan',['--rundir','fresh-run','--spec','source.json']),
 ('approve',['--rundir','fresh-run','--scripted','--quote','synthetic parser text; no approval']),
 ('run',['--rundir','fresh-run']),('status',['--rundir','fresh-run','--write'])])
def test_actual_public_parser_constructs_ordinary_commands(command,tail):
    args=cli.parser().parse_args([command,*tail])
    assert args.command==command and args.rundir==Path('fresh-run')

@pytest.mark.parametrize('command,tail',[
 ('plan',['--rundir','fresh-run','--spec','source.json']),
 ('approve',['--rundir','fresh-run','--scripted','--quote','synthetic parser text; no approval']),
 ('run',['--rundir','fresh-run']),('status',['--rundir','fresh-run','--write'])])
def test_actual_public_main_routes_without_invoking_authority_or_tool(command,tail,monkeypatch):
    calls=[]
    def handler(args):calls.append(args);return 17
    monkeypatch.setattr(cli,'_'+command,handler)
    assert cli.main([command,*tail])==17
    assert len(calls)==1 and calls[0].command==command

@pytest.mark.parametrize('command',list(cli.FOCUSED_COMMANDS))
def test_every_focused_registry_entry_has_exact_relative_module_and_real_main(command,monkeypatch):
    entry=cli.FOCUSED_COMMANDS[command]
    assert type(entry) is tuple and len(entry)==2
    module_name,description=entry
    assert type(module_name) is str and re.fullmatch(r'(workflow|physics|validation|setup)(\.[a-z_][a-z0-9_]*)+',module_name)
    assert type(description) is str and description.strip()
    module=import_module('ravel.'+module_name)
    assert callable(module.main)
    calls=[]
    def observed(args):calls.append(args);return 19
    monkeypatch.setattr(module,'main',observed)
    assert cli.main([command,'--synthetic-routing-sentinel','exact-tail'])==19
    assert calls==[['--synthetic-routing-sentinel','exact-tail']]

@pytest.mark.parametrize('bad',['ravel.workflow.research_protocol',('workflow.research_protocol',),('workflow.research_protocol','help','extra')])
def test_malformed_registry_refuses_before_ordinary_handler(bad,monkeypatch):
    monkeypatch.setitem(cli.FOCUSED_COMMANDS,'research-protocol',bad)
    monkeypatch.setattr(cli,'_plan',lambda *_:pytest.fail('ordinary plan handler reached through malformed registry'))
    assert cli.main(['plan','--rundir','fresh-run','--spec','source.json'])==2
