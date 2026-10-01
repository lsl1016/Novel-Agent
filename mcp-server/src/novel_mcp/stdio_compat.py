"""无依赖的 stdio 兼容适配器,用于冒烟测试和旧版宿主。
生产环境请优先使用 server.py 中的官方 MCP Python SDK v2 适配器。
"""
from __future__ import annotations
import json,sys
from .runtime import call_tool
from .tooldefs import TOOLS

def result(i,data): return {'jsonrpc':'2.0','id':i,'result':data}
def error(i,code,msg): return {'jsonrpc':'2.0','id':i,'error':{'code':code,'message':msg}}
def handle(req):
    i=req.get('id'); m=req.get('method'); p=req.get('params') or {}
    try:
        if m=='initialize': return result(i,{'protocolVersion':p.get('protocolVersion','2025-11-25'),'serverInfo':{'name':'narrative-kg-novel','version':'0.10.0'},'capabilities':{'tools':{'listChanged':False}}})
        if m=='server/discover': return result(i,{'serverInfo':{'name':'narrative-kg-novel','version':'0.10.0'},'capabilities':{'tools':{'listChanged':False}}})
        if m=='ping': return result(i,{})
        if m=='tools/list': return result(i,{'resultType':'complete','tools':TOOLS,'ttlMs':300000,'cacheScope':'public'})
        if m=='tools/call':
            data=call_tool(p.get('name',''),p.get('arguments') or {})
            return result(i,{'resultType':'complete','content':[{'type':'text','text':json.dumps(data,ensure_ascii=False)}],'structuredContent':data})
        if m and m.startswith('notifications/'): return None
        return error(i,-32601,'method not found')
    except Exception as e:return error(i,-32000,str(e))

def main():
    for line in sys.stdin:
        try:req=json.loads(line); out=handle(req)
        except Exception as e:out=error(None,-32700,str(e))
        if out is not None:
            sys.stdout.write(json.dumps(out,ensure_ascii=False,separators=(',',':'))+'\n'); sys.stdout.flush()
if __name__=='__main__':main()
