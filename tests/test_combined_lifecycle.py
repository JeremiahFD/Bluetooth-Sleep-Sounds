import importlib.util
import unittest
from unittest.mock import patch
from pathlib import Path
from audio_output import COMBINED_OUTPUT, COMBINED_WIRED, COMBINED_BT
spec=importlib.util.spec_from_file_location('combined_lifecycle',Path(__file__).parents[1]/'scripts/sleep-sounds-combined-output.py')
helper=importlib.util.module_from_spec(spec);spec.loader.exec_module(helper)

def node(i,name,state='running',serial=None):
 return {'id':i,'type':'PipeWire:Interface:Node','info':{'state':state,'props':{'node.name':name,'object.serial':serial or i}}}

class CombinedLifecycleTests(unittest.TestCase):
 def setUp(self):
  self.sink=node(10,COMBINED_OUTPUT.split('/',1)[1]);self.wired=node(20,COMBINED_WIRED.split('/',1)[1]);self.bt=node(30,COMBINED_BT.split('/',1)[1]);self.nodes={x['id']:x for x in [self.sink,self.wired,self.bt,node(40,'test-player')]}
  self.nodes[50]={'id':50,'type':'PipeWire:Interface:Link','info':{'input-node-id':10,'output-node-id':40,'state':'active'}}
 def test_unused_output_has_no_member_plan(self):
  self.assertEqual(helper.route_plan(self.nodes,COMBINED_BT),(10,{}))
 def test_paused_or_idle_combined_has_no_member_plan(self):
  for state in ['suspended','idle']:
   self.nodes[40]['info']['state']=state;self.assertEqual(helper.route_plan(self.nodes,COMBINED_OUTPUT),(10,{}))
 def test_active_combined_and_rejoining_device(self):
  self.assertEqual(helper.route_plan(self.nodes,COMBINED_OUTPUT),(10,{'wired':(20,20),'bluetooth':(30,30)}))
  del self.nodes[30];self.assertEqual(helper.route_plan(self.nodes,COMBINED_OUTPUT),(10,{'wired':(20,20)}))
  self.nodes[30]=node(30,COMBINED_BT.split('/',1)[1],serial=99)
  self.assertEqual(helper.route_plan(self.nodes,COMBINED_OUTPUT)[1]['bluetooth'],(30,99))
 def test_missing_sink(self):
  del self.nodes[10];self.assertEqual(helper.route_plan(self.nodes,COMBINED_OUTPUT),(None,{}))
 def test_unrelated_sink_is_never_a_member(self):
  self.nodes[60]=node(60,'unrelated');self.assertEqual(set(helper.route_plan(self.nodes,COMBINED_OUTPUT)[1]),{'wired','bluetooth'})
 def test_monitor_partial_update_and_removal(self):
  helper.merge_nodes(self.nodes,[{'id':10,'info':{'state':'suspended'}}])
  self.assertEqual(self.nodes[10]['info']['state'],'suspended');self.assertEqual(self.nodes[10]['info']['props']['node.name'],COMBINED_OUTPUT.split('/',1)[1])
  helper.merge_nodes(self.nodes,[{'id':30,'info':None}]);self.assertNotIn(30,self.nodes)
 def test_properties_are_exact_targets_with_adaptive_resampling(self):
  for label,name in [('wired',COMBINED_WIRED),('bluetooth',COMBINED_BT)]:
   props=helper.member_properties(label);self.assertEqual(props['target.object'],name.split('/',1)[1]);self.assertFalse(props['resample.disable'])
  conf=helper.configuration();self.assertTrue(conf['combine.on-demand-streams']);self.assertEqual(conf['stream.rules'],[])

 def test_metadata_cli_order_and_exact_delete(self):
  with patch.object(helper.subprocess,'run') as run:
   helper.metadata(10,'wired',{'target.object':'test'})
   argv=run.call_args.args[0];self.assertEqual(argv[-1],'Spa:String:JSON');self.assertIn('target.object',argv[-2])
   helper.metadata(10,'wired');argv=run.call_args.args[0];self.assertIn('--delete',argv);self.assertEqual(argv[-1],'combine.on-demand-stream.wired')

 def test_running_sink_without_producer_does_not_keep_members_alive(self):
  self.nodes.pop(50);self.assertEqual(helper.route_plan(self.nodes,COMBINED_OUTPUT),(10,{}))
 def test_link_update_preserves_input_and_output_identity(self):
  helper.merge_nodes(self.nodes,[{'id':50,'info':{'state':'paused'}}])
  self.assertEqual(helper.route_plan(self.nodes,COMBINED_OUTPUT),(10,{}));self.assertEqual(self.nodes[50]['info']['input-node-id'],10)
