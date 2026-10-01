"""无依赖的 HTTP 兼容服务器。

在同一个端口上暴露两种传输方式:

* ``POST /mcp``:供 MCP 客户端使用的无状态 MCP JSON 端点。
* ``POST /api/agent/tools/call/{name}``:供通用 MCP 网关使用的轻量 HTTP 门面,
  这些网关会把任意 JSON HTTP API 注册为 MCP 工具。

该门面刻意把每个成功的工具结果包装成对象
``{"errNo": 0, "errMsg": "success", "data": ...}``,
以便要求输出 schema 以对象为根的网关也能注册原生结果为数组的工具。
"""
from __future__ import annotations
import argparse,json,os
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from urllib.parse import unquote,urlparse
from .stdio_compat import handle
from .runtime import call_tool
from .auth import auth_enabled, resolve_role, tool_allowed

PROTOCOL='2026-07-28'
FACADE_PREFIX='/api/agent/tools/call/'


def _facade_token_ok(headers) -> bool:
    if not auth_enabled():
        return True
    role, err = resolve_role(dict(headers.items()) if hasattr(headers, 'items') else dict(headers))
    return err == 0


def facade_call(name:str,args:dict|None,headers:dict|None=None):
    role, err = resolve_role(headers or {})
    if err != 0:
        return 401,{'errNo':err,'errMsg':'unauthorized','data':None}
    ok, reason = tool_allowed(role, name, args or {})
    if not ok:
        return 200,{'errNo':40301,'errMsg':f'role {role} denied: {reason}','data':None}
    try:
        data=call_tool(name,args or {})
        return 200,{'errNo':0,'errMsg':'success','data':data}
    except KeyError as e:
        return 200,{'errNo':40401,'errMsg':str(e),'data':None}
    except (TypeError,ValueError) as e:
        return 200,{'errNo':40001,'errMsg':str(e),'data':None}
    except Exception as e:
        return 200,{'errNo':50001,'errMsg':str(e),'data':None}


class Handler(BaseHTTPRequestHandler):
    server_version='NarrativeKGMCP/0.10'
    def log_message(self,fmt,*args):
        super().log_message(fmt,*args)

    def _read_json(self):
        n=int(self.headers.get('Content-Length','0'))
        raw=self.rfile.read(n) if n else b'{}'
        value=json.loads(raw.decode('utf-8'))
        if value is None:
            return {}
        if not isinstance(value,dict):
            raise ValueError('request body must be a JSON object')
        return value

    def _json(self,status:int,out:dict,protocol:bool=False):
        data=json.dumps(out,ensure_ascii=False,separators=(',',':')).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type','application/json; charset=utf-8')
        self.send_header('Content-Length',str(len(data)))
        if protocol:
            self.send_header('MCP-Protocol-Version',PROTOCOL)
        self.end_headers(); self.wfile.write(data)

    def do_POST(self):
        path=urlparse(self.path).path
        if path.rstrip('/')=='/mcp':
            try:
                req=self._read_json(); out=handle(req)
            except Exception as e:
                out={'jsonrpc':'2.0','id':None,'error':{'code':-32700,'message':str(e)}}
            if out is None:
                self.send_response(202); self.send_header('MCP-Protocol-Version',PROTOCOL); self.end_headers(); return
            self._json(200,out,protocol=True); return

        if path.startswith(FACADE_PREFIX):
            if not _facade_token_ok(self.headers):
                self._json(401,{'errNo':40101,'errMsg':'unauthorized','data':None}); return
            name=unquote(path[len(FACADE_PREFIX):]).strip('/')
            if not name:
                self._json(404,{'errNo':40401,'errMsg':'tool name is required','data':None}); return
            try:
                args=self._read_json()
            except Exception as e:
                self._json(400,{'errNo':40000,'errMsg':str(e),'data':None}); return
            status,out=facade_call(name,args,headers=dict(self.headers.items()))
            self._json(status,out); return

        self.send_error(404)


def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--host',default='127.0.0.1'); ap.add_argument('--port',type=int,default=8765); a=ap.parse_args()
    srv=ThreadingHTTPServer((a.host,a.port),Handler)
    print(f'Narrative-KG HTTP listening on http://{a.host}:{a.port}/mcp and {FACADE_PREFIX}{{name}}',flush=True)
    srv.serve_forever()
if __name__=='__main__': main()
