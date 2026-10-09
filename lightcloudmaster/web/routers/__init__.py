"""按域拆分的 API 路由：chat / register / report / review / assessment / privacy /
appeals / resources。

装配（create_app）在 web/__init__.py，鉴权与图辅助在 web/deps.py，请求模型在
web/schemas.py。

红线：路由函数只做「鉴权 → 调服务/DAL → 组装响应」，业务规则一律在 services/ 与
storage/ 层；审核台全部端点必须经 require_reviewer（令牌走 Authorization header，不进 URL）。
"""
