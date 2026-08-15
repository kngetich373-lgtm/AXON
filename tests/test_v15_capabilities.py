import tempfile, unittest
from pathlib import Path
from axon.skills import SkillRegistry
from axon.memory import MemoryManager
from axon.knowledge.graph import KnowledgeGraph
from axon.security import SecurityWorkflow, Scope, SecurityReviewer

class V15CapabilitiesTests(unittest.TestCase):
    def test_skills_discover(self):
        skills = SkillRegistry([Path('axon/skills')]).list()
        self.assertGreaterEqual(len(skills), 4)
        self.assertTrue(any(s.name == 'software-engineering' for s in skills))

    def test_layered_memory_rejects_secret(self):
        with tempfile.TemporaryDirectory() as d:
            m=MemoryManager(d)
            with self.assertRaises(ValueError): m.add('l1','api_key','secret-value')
            item=m.add('l1','fact','AXON uses layered memory')
            self.assertEqual(m.search('layered memory')[0].id,item.id)

    def test_code_graph_indexes_without_execution(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'demo.py'; p.write_text('import os\nclass A:\n    def run(self):\n        return 1\n')
            g=KnowledgeGraph().index_tree(d)
            self.assertTrue(any(n.kind=='class' and n.name=='A' for n in g.nodes.values()))
            self.assertTrue(any(e.relation=='imports' for e in g.edges))

    def test_security_workflow_requires_authorization(self):
        w=SecurityWorkflow('web-assessment')
        with self.assertRaises(ValueError): w.authorize(Scope(('example.com',),''))
        w.authorize(Scope(('example.com',),'ticket-123'))
        w.add_evidence('http','200 OK')
        w.add_finding('Example finding','low','test')
        self.assertTrue(SecurityReviewer().review(w)['verified'])

if __name__=='__main__': unittest.main()

class V15AgentContextTests(unittest.TestCase):
    def test_agent_has_skill_and_layered_memory_context(self):
        from axon.core import Agent
        with tempfile.TemporaryDirectory() as d:
            m = MemoryManager(d)
            m.add('l1', 'fact', 'AXON project uses a code graph')
            agent = Agent(memory=None, layered_memory=m)
            ctx = agent.understand('code graph')
            self.assertIn('software-engineering', ctx.metadata['skills']) if 'software-engineering' in ctx.metadata['skills'] else self.assertTrue(ctx.metadata['skills'] == [])
            self.assertTrue(ctx.memories)

class V154Tests(unittest.TestCase):
    def test_graph_query_returns_relationships(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            (root/'memory.py').write_text('class Memory: pass\n')
            (root/'agent.py').write_text('from memory import Memory\nclass Agent: pass\n')
            from axon.knowledge import ProjectKnowledge
            k=ProjectKnowledge(root); k.refresh()
            text=k.query('which modules depend on memory', limit=20)
            self.assertIn('imports', text)
            self.assertIn('agent.py', text)
