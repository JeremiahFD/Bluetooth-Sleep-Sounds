import copy
import http.client
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

from remote_controls import RemoteStore, InputPolicy, Learning, StickAxis, new_layout, validate_layout
from remote_input import RemoteManager, LinuxNode, EVENT, discover
from test_server import FakePlayer
from server import Controller, Server


def layout(**extra):
    return validate_layout({**new_layout(), 'regular_delay': 0, 'modified_delay': 0,
        'modifiers': ['k:310'], 'bindings': [
            {'tokens': ['k:304'], 'modified': False, 'action': 'play_pause'},
            {'tokens': ['k:305'], 'modified': False, 'action': 'stop'},
            {'tokens': ['k:304','k:305'], 'modified': False, 'action': 'loop'},
            {'tokens': ['k:304'], 'modified': True, 'action': 'next'},
            {'tokens': ['k:305'], 'modified': True, 'action': 'volume_up'},
            {'tokens': ['k:310'], 'modified': False, 'action': 'normalization'},
            {'tokens': ['a:0:+'], 'modified': False, 'action': 'next'},
        ], **extra})


class PolicyTests(unittest.TestCase):
    def setUp(self):
        self.now = 100
        self.policy = InputPolicy(layout(), lambda: self.now)

    def press(self, token):
        self.assertIsNone(self.policy.event(token, True))
        return self.policy.event(token, False)

    def test_complete_press_release_and_no_os_repeat(self):
        self.assertIsNone(self.policy.event('k:304', True))
        self.assertIsNone(self.policy.event('k:304', True))
        self.assertEqual(self.policy.event('k:304', False), 'play_pause')
        self.assertIsNone(self.policy.event('k:304', False))

    def test_two_button_chord_does_not_run_either_single(self):
        self.policy.event('k:304', True); self.policy.event('k:305', True)
        self.assertEqual(self.policy.event('k:304', False), 'loop')
        self.assertIsNone(self.policy.event('k:305', False))

    def test_hold_modifier_and_use_different_buttons_without_repressing_it(self):
        self.policy.event('k:310', True)
        self.assertEqual(self.press('k:304'), 'next')
        self.assertEqual(self.press('k:305'), 'volume_up')
        self.assertEqual(self.press('k:304'), 'next')
        self.assertIsNone(self.policy.event('k:310', False))
        self.assertEqual(self.press('k:304'), 'play_pause')

    def test_modifier_alone_uses_modified_shared_delay(self):
        self.policy = InputPolicy(layout(modified_delay=2), lambda: self.now)
        self.assertEqual(self.press('k:310'), 'normalization')
        self.policy.event('k:310', True)
        self.assertIsNone(self.press('k:305'))
        self.now += 2
        self.assertEqual(self.press('k:305'), 'volume_up')

    def test_two_global_cooldown_buckets_not_per_button(self):
        self.policy = InputPolicy(layout(regular_delay=2, modified_delay=3), lambda: self.now)
        self.assertEqual(self.press('k:304'), 'play_pause')
        self.assertIsNone(self.press('k:305'))
        self.policy.event('k:310', True)
        self.assertEqual(self.press('k:305'), 'volume_up')
        self.assertIsNone(self.press('k:304'))
        self.now += 3
        self.assertEqual(self.press('k:304'), 'next')
        self.policy.event('k:310', False)
        self.assertEqual(self.press('k:305'), 'stop')

    def test_release_modifier_first_does_not_change_chord_to_normal(self):
        self.policy.event('k:310', True); self.policy.event('k:304', True)
        self.assertIsNone(self.policy.event('k:310', False))
        self.assertEqual(self.policy.event('k:304', False), 'next')

    def test_any_button_overrides_bindings_without_mutating_them(self):
        value = layout(any_button=True, any_action='play_default')
        self.policy = InputPolicy(value)
        self.assertEqual(self.policy.event('k:305', True), 'play_default')
        self.assertIsNone(self.policy.event('k:305', False))
        self.assertEqual(self.policy.layout['bindings'], value['bindings'])

    def test_any_button_stale_held_key_does_not_block_next_button(self):
        policy = InputPolicy(layout(any_button=True, any_action='play_stop', regular_delay=.5), lambda:self.now)
        self.assertEqual(policy.event('k:114', True), 'play_stop')
        self.now += 1
        self.assertEqual(policy.event('k:115', True), 'play_stop')
        self.assertIsNone(policy.event('k:115', False))
        self.now += 1
        self.assertEqual(policy.event('k:115', True), 'play_stop')

    def test_any_button_shared_cooldown_filters_duplicate_interfaces(self):
        policy = InputPolicy(layout(any_button=True, any_action='play_stop', regular_delay=.5), lambda:self.now)
        self.assertEqual(policy.event('k:114', True), 'play_stop')
        self.assertIsNone(policy.event('k:304', True))
        self.assertIsNone(policy.event('k:114', False))
        self.now += .6
        self.assertEqual(policy.event('a:0:+', True), 'play_stop')

    def test_unmapped_button_does_not_use_cooldown(self):
        self.policy = InputPolicy(layout(regular_delay=2), lambda: self.now)
        self.assertIsNone(self.press('k:100'))
        self.assertEqual(self.press('k:304'), 'play_pause')

    def test_stick_direction_then_return_to_center(self):
        self.assertEqual(self.press('a:0:+'), 'next')

    def test_learning_chord_and_modifier_stays_down(self):
        learn = Learning('remote', ['k:310'])
        for token in ['k:310','k:304','k:305']:
            learn.event(token, True)
        learn.event('k:305', False)
        self.assertIsNone(learn.result)
        learn.event('k:304', False)
        self.assertEqual(learn.result, {'tokens':['k:304','k:305'], 'modified':True})
        self.assertIn('k:310', learn.held)

    def test_learning_timeout_and_no_release_without_down(self):
        learn = Learning('remote', clock=lambda:self.now)
        learn.event('k:304', False)
        self.assertIsNone(learn.result)
        learn.event('k:304', True)
        self.now += 21
        learn.event('k:304', False)
        self.assertIsNone(learn.result)

    def test_axis_deadzone_hysteresis_and_no_drift_repeats(self):
        axis = StickAxis(-100,100,.35)
        self.assertEqual(axis.update(10), [])
        self.assertEqual(axis.update(80), [(1,True)])
        self.assertEqual(axis.update(90), [])
        self.assertEqual(axis.update(30), [])
        self.assertEqual(axis.update(20), [(1,False)])
        self.assertEqual(axis.update(-80), [(-1,True)])
        self.assertEqual(axis.update(80), [(-1,False),(1,True)])

    def test_unipolar_trigger_rest_is_not_a_held_negative_direction(self):
        axis = StickAxis(0,255,.35,True)
        self.assertEqual(axis.update(0), [])
        self.assertEqual(axis.update(250), [(1,True)])
        self.assertEqual(axis.update(0), [(1,False)])

    def test_bad_layouts_and_duplicates_are_rejected(self):
        for change in [{'regular_delay':True},{'modified_delay':float('nan')},{'dead_zone':.99},
                       {'modifiers':['k:900']},{'any_action':'shell'},{'bindings':layout()['bindings']*2}]:
            with self.subTest(change=change), self.assertRaises(ValueError):
                layout(**change)


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'remotes.json'
        self.store = RemoteStore(self.path)
        self.devices = [{'id':'a'*32,'name':'VR BOX','nodes':['/dev/input/event4']}]

    def tearDown(self):
        self.temp.cleanup()

    def change(self, action, **details):
        return self.store.change({'action':action,'revision':self.store.state['revision'],**details},
            self.devices, {'none'}, lambda name: None)

    def add(self):
        return self.change('add',device='a'*32)['remotes'][0]

    def test_new_remote_disabled_and_app_only_requested(self):
        row = self.add()
        self.assertFalse(row['enabled']); self.assertTrue(row['app_only'])
        self.assertEqual(RemoteStore(self.path).snapshot(),self.store.snapshot())

    def test_current_track_choice_is_persisted_without_a_filename_probe(self):
        row = self.add()
        validate = Mock(side_effect=AssertionError('Dynamic choice is not a filename'))
        self.store.change({'action':'save_remote','revision':self.store.state['revision'],
            'remote':row['id'],'values':{'default_track':'@current'}},self.devices,{'none'},validate)
        validate.assert_not_called()
        self.assertEqual(RemoteStore(self.path).snapshot()['remotes'][0]['default_track'], '@current')

    def test_requires_detected_identity_not_arbitrary_input_path(self):
        with self.assertRaises(ValueError):
            self.change('add',device='/dev/input/event0')

    def test_stale_revision_leaves_disk_unchanged(self):
        self.add(); before = self.path.read_bytes()
        with self.assertRaisesRegex(ValueError,'elsewhere'):
            self.store.change({'action':'add','revision':0}, [], set(), lambda _:None)
        self.assertEqual(before,self.path.read_bytes())

    def test_remove_keeps_reusable_layout(self):
        row=self.add(); lid=row['layout']
        self.change('remove',remote=row['id'])
        self.assertEqual(self.store.state['remotes'],[])
        self.assertEqual(self.store.state['layouts'][0]['id'],lid)

    def test_copy_layout_and_cannot_delete_in_use(self):
        row=self.add()
        self.change('copy_layout',layout=row['layout'],name='SNES')
        self.assertEqual(len(self.store.state['layouts']),2)
        with self.assertRaisesRegex(ValueError,'another layout'):
            self.change('delete_layout',layout=row['layout'])

    def test_disable_keeps_bindings_and_unfamiliar_fields(self):
        row=self.add()
        self.store.state['future']={'keep':True}
        self.store.state['remotes'][0]['future_remote']='keep'
        self.change('save_layout',layout=row['layout'],values={'any_button':True})
        self.change('save_remote',remote=row['id'],values={'enabled':False})
        loaded=RemoteStore(self.path)
        self.assertTrue(loaded.state['future']['keep'])
        self.assertEqual(loaded.state['remotes'][0]['future_remote'],'keep')
        self.assertTrue(loaded.state['layouts'][0]['any_button'])

    def test_corrupt_or_newer_file_never_overwritten(self):
        for payload in ['{broken',json.dumps({'version':2})]:
            self.path.write_text(payload)
            store=RemoteStore(self.path)
            self.assertTrue(store.read_error)
            with self.assertRaises(ValueError):store.change({'revision':0},[],set(),lambda _:None)
            self.assertEqual(self.path.read_text(),payload)

    def test_atomic_write_failure_does_not_publish_memory(self):
        row=self.add(); before=copy.deepcopy(self.store.state)
        with patch('remote_controls.atomic_json',side_effect=OSError('disk full')):
            with self.assertRaises(OSError):self.change('save_remote',remote=row['id'],values={'name':'Changed'})
        self.assertEqual(self.store.state,before)


class ManagerTests(unittest.TestCase):
    # Independent manager checks use the same persisted device fixture.
    setUp = StoreTests.setUp
    tearDown = StoreTests.tearDown
    change = StoreTests.change
    add = StoreTests.add
    def manager(self, fail_second=False, held=()):
        row=self.add()
        self.change('save_remote',remote=row['id'],values={'enabled':True})
        nodes=[]
        def factory(path,exclusive,dead_zone):
            if fail_second and nodes:raise PermissionError()
            n=Mock();n.held=set(held);nodes.append(n);return n
        self.devices[0]['nodes']=['/dev/input/event4','/dev/input/event5']
        manager=RemoteManager(self.store,Mock(),lambda:self.devices,factory)
        return manager,row,nodes

    def test_composite_group_all_nodes_captured_and_released(self):
        manager,row,nodes=self.manager()
        manager._sync()
        self.assertEqual(len(nodes),2)
        self.assertTrue(manager.health[row['id']]['app_only_active'])
        manager.release_all()
        self.assertFalse(manager.sessions)
        for node in nodes:node.close.assert_called_once()

    def test_partial_grab_failure_releases_previous_nodes(self):
        manager,row,nodes=self.manager(True)
        manager._sync()
        self.assertFalse(manager.sessions)
        self.assertFalse(manager.health[row['id']]['app_only_active'])
        nodes[0].close.assert_called_once()

    def test_unused_endpoint_axes_do_not_block_buttons_on_connection(self):
        manager,row,_=self.manager(held=['a:0:-','a:1:-'])
        manager._sync()
        session=manager.sessions[row['id']]
        self.assertFalse(session['blocked'])
        self.assertEqual(session['policy'].held,set())
        manager.dispatch.assert_not_called()

    def test_button_held_on_connection_still_requires_release(self):
        manager,row,_=self.manager(held=['a:0:-','k:30'])
        manager._sync()
        self.assertTrue(manager.sessions[row['id']]['blocked'])
        manager.dispatch.assert_not_called()

    def test_disconnect_and_reconnect_never_dispatch_actions(self):
        manager,row,nodes=self.manager()
        manager._sync();self.devices.clear();manager._sync()
        self.assertFalse(manager.sessions)
        manager.dispatch.assert_not_called()

    def test_saved_changes_reject_queued_old_actions(self):
        manager,row,nodes=self.manager();manager._sync()
        generation=manager.generation
        self.assertTrue(manager.dispatch_if_current(generation,row,'play_pause'))
        manager.invalidate()
        self.assertFalse(manager.dispatch_if_current(generation,row,'play_pause'))

    def test_learning_requires_app_only_and_available_service(self):
        manager,row,_=self.manager()
        manager.supported=True;manager.thread=Mock();manager.thread.is_alive.return_value=True
        self.change('save_remote',remote=row['id'],values={'app_only':False})
        with self.assertRaisesRegex(ValueError,'App only'):manager.learn(row['id'])

    def test_learning_cannot_start_until_all_interfaces_are_captured(self):
        manager,row,nodes=self.manager(True)
        manager.supported=True;manager.thread=Mock();manager.thread.is_alive.return_value=True
        with self.assertRaisesRegex(ValueError,'access denied or busy'):
            manager.learn(row['id'])
        self.assertIsNone(manager.learning)
        self.assertFalse(manager.sessions)
        nodes[0].close.assert_called_once()

    def test_learning_expiry_restores_no_stuck_modifier_state(self):
        manager,row,_=self.manager();manager._sync()
        manager.learning=Learning(row['id'],clock=lambda:0)
        manager.learning.deadline=-1
        previous=manager.generation;manager._sync()
        self.assertIsNone(manager.learning)
        self.assertGreater(manager.generation,previous)
        self.assertEqual(manager.sessions[row['id']]['policy'].held,set())


class ReaderTests(unittest.TestCase):
    def node(self):
        n=LinuxNode.__new__(LinuxNode);n.fd=17;n.axes={0:StickAxis(-100,100,.35)};n.buffer=b'';n.held=set();return n

    def test_pointer_motion_and_autorepeat_not_actions(self):
        node=self.node()
        packet=b''.join(EVENT.pack(0,0,*x) for x in [(2,0,80),(1,304,2),(1,304,1),(1,304,0)])
        with patch('remote_input.os.read',return_value=packet):
            self.assertEqual(node.read(),[('k:304',True),('k:304',False)])

    def test_fragmented_kernel_records(self):
        node=self.node();packet=EVENT.pack(0,0,1,304,1)
        with patch('remote_input.os.read',side_effect=[packet[:5],packet[5:]]):
            self.assertEqual(node.read(),[])
            self.assertEqual(node.read(),[('k:304',True)])

    def test_overflow_releases_session_instead_of_guessing_held_keys(self):
        node=self.node()
        with patch('remote_input.os.read',return_value=EVENT.pack(0,0,0,3,0)), self.assertRaises(OSError):node.read()

    def test_bluetooth_composite_identity_and_same_name_separate_devices(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            for i,unique in enumerate(['02:00:00:00:00:06','02:00:00:00:00:06','02:00:00:00:00:05']):
                d=root/f'event{i}'/'device';(d/'id').mkdir(parents=True)
                for p,value in [('id/bustype','0005'),('id/vendor','1234'),('id/product','5678'),('uniq',unique),('name','VR BOX')]:
                    (d/p).write_text(value)
            with patch('remote_input.sys.platform','linux'):
                groups=discover(root,root/'dev')
            self.assertEqual(len(groups),2)
            self.assertEqual(sorted(len(g['nodes']) for g in groups),[1,2])


class DispatchTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.player=FakePlayer();self.c=Controller(Path(self.temp.name),self.player)
        self.manager=Mock();self.manager.dispatch_if_current.return_value=True
        self.remote={'id':'r','profile':'none','default_track':'Rain.wav'}
        (self.c.tracks/'Rain.wav').write_bytes(b'fixture')
        self.player.properties['audio-device-list'].append({'name':'pulse/speaker'})
        self.c.output='pulse/speaker'

    def tearDown(self):self.temp.cleanup()

    def action(self,action):self.c.remote_action(self.manager,1,self.remote,action)

    def test_play_pause_starts_only_on_actual_action_then_pauses(self):
        self.action('play_pause');self.assertEqual(self.c.selected,'Rain.wav')
        self.action('play_pause');self.assertTrue(self.player.properties['pause'])

    def test_play_stop_starts_stops_and_starts_without_learning(self):
        self.action('play_stop');self.assertEqual(self.c.selected,'Rain.wav')
        self.c.set_timer(1)
        self.action('play_stop');self.assertTrue(self.player.properties['idle-active']);self.assertIsNone(self.c.deadline)
        self.action('play_stop');self.assertFalse(self.player.properties['idle-active'])

    def test_normalization_keeps_existing_dsp_exclusivity(self):
        self.action('normalization');self.assertTrue(self.c.normalization)
        self.assertTrue(self.c.audio_processing['bypass'])
        self.action('processing');self.assertFalse(self.c.normalization)
        self.assertFalse(self.c.audio_processing['bypass'])

    def test_current_track_choice_resolves_at_action_and_survives_restart(self):
        self.remote['default_track'] = '@current'
        with self.assertRaisesRegex(ValueError, 'Play a track once'):
            self.action('play_default')
        self.assertEqual(self.player.calls, [])
        self.c.play('Rain.wav')
        self.c.stop()
        self.action('play_default')
        self.assertEqual(self.c.selected, 'Rain.wav')
        (self.c.tracks/'Other.wav').write_bytes(b'fixture')
        self.c.play('Other.wav')
        self.c.stop()
        self.action('play_default')
        self.assertEqual(self.c.selected, 'Other.wav')
        self.c = Controller(Path(self.temp.name), FakePlayer())
        self.c.player.properties['audio-device-list'].append({'name':'pulse/speaker'})
        self.c.output = 'pulse/speaker'
        self.action('play_default')
        self.assertEqual(self.c.selected, 'Other.wav')

    def test_alarm_controls_protected(self):
        self.c.mode='alarm'
        with self.assertRaisesRegex(ValueError,'alarm'):self.action('stop')
        self.assertEqual(self.player.calls,[])

    def test_stale_action_cannot_start_audio(self):
        self.manager.dispatch_if_current.return_value=False
        self.action('play_default');self.assertEqual(self.player.calls,[])

    def test_volume_clamped_and_timer_no_playback(self):
        self.c.volume=99;self.action('volume_up');self.assertEqual(self.c.volume,100)
        self.action('timer');self.assertIsNotNone(self.c.deadline)
        self.action('cancel_timer');self.assertIsNone(self.c.deadline)
        self.assertNotIn('loadfile',[x[0] for x in self.player.calls])


class RemoteApiTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.c=Controller(Path(self.temp.name),FakePlayer())
        self.c.remote_manager.discoverer=lambda:[{'id':'a'*32,'name':'VR BOX','nodes':[],'transport':'Preview','readable':False}]
        self.server=Server(('127.0.0.1',0),self.c,['127.0.0.1'])
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()

    def tearDown(self):
        self.server.shutdown();self.server.server_close();self.thread.join();self.temp.cleanup()

    def request(self,method='GET',body=None,token=True):
        connection=http.client.HTTPConnection('127.0.0.1',self.server.server_port)
        headers={'Content-Type':'application/json'}
        if token:headers['X-Sleep-Token']=self.c.token
        connection.request(method,'/api/remotes',None if body is None else json.dumps(body),headers)
        response=connection.getresponse();status=response.status;result=json.loads(response.read());connection.close()
        return status,result

    def test_discovery_and_add_without_enabling_or_opening_any_input(self):
        status,result=self.request();self.assertEqual(status,200);self.assertEqual(result['devices'][0]['name'],'VR BOX')
        status,result=self.request('POST',{'action':'add','revision':0,'device':'a'*32})
        self.assertEqual(status,200);self.assertFalse(result['remotes'][0]['enabled'])
        self.assertFalse(self.c.remote_manager.sessions)

    def test_mutation_requires_existing_same_origin_token(self):
        status,_=self.request('POST',{'action':'release_all'},False)
        self.assertEqual(status,403);self.assertFalse(self.c.remote_manager.suspended)

    def test_release_and_resume_dont_change_saved_layouts(self):
        before=self.c.remote_store.snapshot()
        self.assertEqual(self.request('POST',{'action':'release_all'})[0],200)
        self.assertTrue(self.c.remote_manager.suspended)
        self.assertEqual(self.request('POST',{'action':'resume'})[0],200)
        self.assertEqual(self.c.remote_store.snapshot(),before)

    def test_emergency_release_does_not_wait_for_playback_lock(self):
        self.c.lock.acquire()
        try:
            status,result=self.request('POST',{'action':'release_all'})
            self.assertEqual(status,200)
            self.assertTrue(result['suspended'])
        finally:
            self.c.lock.release()

    def test_unsupported_or_unavailable_learning_returns_actionable_error(self):
        status,result=self.request('POST',{'action':'learn','remote':'missing'})
        self.assertEqual(status,400);self.assertIn('unavailable',result['error'])

if __name__=='__main__':unittest.main()
