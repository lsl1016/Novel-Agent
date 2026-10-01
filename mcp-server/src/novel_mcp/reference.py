from __future__ import annotations
import csv,json
from pathlib import Path

class ReferenceLibrary:
    """对 Narrative-KG 参考模式的只读访问。

    只返回结构化元数据。刻意排除源文与证据引文,
    使新故事学到的是机制而非措辞。
    """
    NEED_MAP={
        'partial_reveal': {'LADDERED_REVEAL'},
        'reversal': {'BELIEF_REVERSAL','FALSE_CLOSURE_OR_REOPENING'},
        'payoff': {'EMOTION_DEBT_PAYOFF'},
        'reinterpretation': {'RETROSPECTIVE_REINTERPRETATION'},
        'cross_arc': {'CROSS_ARC_PERSISTENCE'},
        'long_fuse': {'LONG_FUSE_MYSTERY','VERIFIED_LONG_FORESHADOW'},
    }
    QUERY_ALIASES={
        'identity_mystery': {'LONG_FUSE_MYSTERY','VERIFIED_LONG_FORESHADOW','LADDERED_REVEAL','BELIEF_REVERSAL','EMOTION_DEBT_PAYOFF'},
        'belief_reversal': {'BELIEF_REVERSAL'},
        'emotion_payoff': {'EMOTION_DEBT_PAYOFF'},
        'reinterpretation': {'RETROSPECTIVE_REINTERPRETATION'},
        'false_closure': {'FALSE_CLOSURE_OR_REOPENING'},
    }
    def __init__(self,root:str|Path|None=None):
        self.root=Path(root) if root else None
        self.patterns=[]; self.thread_scores={}; self.nodes={}
        if self.root and self.root.exists(): self._load()
    def _find(self,*names):
        for n in names:
            p=self.root/n
            if p.exists():return p
        return None
    def _load(self):
        p=self._find('pattern_instances.jsonl','patterns/pattern_instances.jsonl')
        if p:self.patterns=[json.loads(x) for x in p.read_text(encoding='utf-8-sig').splitlines() if x.strip()]
        p=self._find('thread_scores.csv','metrics/thread_scores.csv')
        if p:
            with p.open(encoding='utf-8-sig',newline='') as f:self.thread_scores={r.get('thread_key',''):r for r in csv.DictReader(f)}
        p=self._find('phase2_graph.json','graph.json')
        if p:
            obj=json.loads(p.read_text(encoding='utf-8')); self.nodes={n['id']:n for n in obj.get('nodes',[])}
    def _capabilities(self,types:set[str], node_ids:list[str]):
        node_types={self.nodes[n].get('type') for n in node_ids if n in self.nodes}
        return {
            'partial_reveal': bool(types & self.NEED_MAP['partial_reveal']) or 'Reveal' in node_types,
            'reversal': bool(types & self.NEED_MAP['reversal']),
            'payoff': bool(types & self.NEED_MAP['payoff']) or 'Payoff' in node_types,
            'reinterpretation': bool(types & self.NEED_MAP['reinterpretation']),
            'cross_arc': bool(types & self.NEED_MAP['cross_arc']),
            'long_fuse': bool(types & self.NEED_MAP['long_fuse']),
        }
    def search(self,pattern='',min_span=0,need=None,limit=10):
        need=[str(x).lower() for x in (need or [])]
        q=pattern.strip().lower(); wanted=self.QUERY_ALIASES.get(q,set())
        grouped={}
        for p in self.patterns:
            if p.get('status')!='detected':continue
            for tk in p.get('thread_keys',[]) or ['unknown']:
                g=grouped.setdefault(tk,{'thread_key':tk,'patterns':[],'node_ids':[],'score':0.0,'span':0})
                g['patterns'].append(p); g['node_ids'] += p.get('evidence_node_ids',[]); g['score']=max(g['score'],float(p.get('score') or 0));
                sp=int((p.get('features') or {}).get('span') or ((p.get('chapter_end') or 0)-(p.get('chapter_start') or 0))); g['span']=max(g['span'],sp)
        out=[]
        for tk,g in grouped.items():
            score_row=self.thread_scores.get(tk,{})
            try: span=max(g['span'],int(float(score_row.get('span_chapters') or 0)))
            except Exception: span=g['span']
            if span<min_span:continue
            types={str(p.get('pattern_type','')).upper() for p in g['patterns']}
            if wanted and not (types & wanted):continue
            if q and not wanted and q not in tk.lower() and not any(q in t.lower() for t in types):continue
            caps=self._capabilities(types,g['node_ids'])
            coverage=sum(1 for n in need if caps.get(n, False)); ratio=1.0 if not need else coverage/len(need)
            stages=[]
            for nid in dict.fromkeys(g['node_ids']):
                n=self.nodes.get(nid)
                if not n:continue
                props=n.get('properties') or {}
                stages.append({'type':n.get('type'),'chapter':n.get('chapter'),'reveal_level':props.get('reveal_level'),'holder':props.get('holder'),'stance':props.get('stance')})
            stages=sorted(stages,key=lambda x:(x.get('chapter') if x.get('chapter') is not None else 10**9,x.get('type') or ''))[:20]
            out.append({'reference_thread_key':tk,'span':span,'pattern_types':sorted(types),'capabilities':caps,'need_coverage':ratio,'missing_need':[n for n in need if not caps.get(n,False)],'narrative_leverage':score_row.get('NarrativeLeverageScore'),'stage_sequence':stages,'source':'REFERENCE_GRAPH_STRUCTURE_ONLY'})
        out.sort(key=lambda x:(-x['need_coverage'],-float(x.get('narrative_leverage') or 0),-x['span'],x['reference_thread_key']))
        return out[:limit]
