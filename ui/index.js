(function () {
  var Q = window.QwenPaw;
  if (!Q || !Q.host || !Q.host.React || !Q.registerRoutes) return;
  var React = Q.host.React;
  var antd = Q.host.antd;
  var h = React.createElement;
  var APP = "/zhiyun-chanjet-hub";
  var FONT = "system-ui, -apple-system, 'Segoe UI', 'Microsoft YaHei', sans-serif";
  var BLUE = "#1f5ed6";

  function readToken() {
    try { return window.localStorage.getItem("zhiyun_token") || ""; } catch (e) { return ""; }
  }
  function request(path, body, method) {
    var headers = Object.assign({ "Content-Type": "application/json" }, (function () {
      try { var t = readToken(); return t ? { Authorization: "Bearer " + t } : {}; } catch (e) { return {}; }
    })());
    return Q.host.fetch(path, {
      method: method || (body !== undefined ? "POST" : "GET"),
      headers: headers,
      body: body === undefined ? undefined : JSON.stringify(body)
    }).then(function (response) {
      return response.json().catch(function () { return {}; }).then(function (data) {
        if (!response.ok) throw new Error(data.detail || ("HTTP " + response.status));
        return data;
      });
    });
  }

  var ENTITY_OPTIONS = [
    { value: "sales_delivery", label: "销售发货单" },
    { value: "sales_order", label: "销售订单" },
    { value: "purchase_order", label: "采购订单" },
    { value: "purchase_receipt", label: "采购入库单" },
    { value: "sale_out", label: "销售出库单" }
  ];
  var COLUMNS = [
    { title: "单据编号", dataIndex: "order_no", width: 160 },
    { title: "往来单位", dataIndex: "customer_name", width: 200 },
    { title: "单据日期", dataIndex: "order_date", width: 110 },
    { title: "状态", dataIndex: "status", width: 100 },
    { title: "金额", dataIndex: "total_amount", width: 120 }
  ];

  function ChanjetHub() {
    var message = antd.App.useApp().message;
    var credState = React.useState({ configured: false, app_key: "", app_secret: "", open_token: "", api_root: "https://openapi.chanjet.com/tplus/api/v2" });
    var cred = credState[0], setCred = credState[1];
    var testState = React.useState(null), testResult = testState[0], setTestResult = testState[1];
    var entityState = React.useState("sales_delivery"), entity = entityState[0], setEntity = entityState[1];
    var rangeState = React.useState({ from: "", to: "" }), range = rangeState[0], setRange = rangeState[1];
    var rowsState = React.useState([]), rows = rowsState[0], setRows = rowsState[1];
    var dcState = React.useState(null), dcInfo = dcState[0], setDcInfo = dcState[1];
    var loadingState = React.useState(false), loading = loadingState[0], setLoading = loadingState[1];
    var busyState = React.useState(""), busy = busyState[0], setBusy = busyState[1];

    function loadCred() {
      request(APP + "/credentials").then(function (data) {
        if (data.configured) setCred(function (prev) { return Object.assign({}, prev, { app_key_masked: data.app_key_masked, configured: true }); });
      }).catch(function () {});
    }
    React.useEffect(function () { loadCred(); }, []);

    function saveCred() {
      if (!cred.app_key || !cred.app_secret || !cred.open_token) { message.warning("appKey / appSecret / openToken 均必填"); return; }
      setBusy("save");
      request(APP + "/credentials", {
        app_key: cred.app_key, app_secret: cred.app_secret,
        open_token: cred.open_token, api_root: cred.api_root
      }).then(function () {
        message.success("凭据已保存");
        loadCred();
      }).catch(function (e) { message.error(e.message); }).finally(function () { setBusy(""); });
    }
    function testConn() {
      setBusy("test"); setTestResult(null);
      request(APP + "/test").then(function (r) {
        setTestResult(r);
        if (r.ok) message.success("连通成功");
      }).catch(function (e) { setTestResult({ ok: false, error: e.message }); })
        .finally(function () { setBusy(""); });
    }
    function fetchData() {
      setLoading(true); setDcInfo(null);
      request(APP + "/fetch", {
        entity: entity, page_size: 20, page_index: 0,
        date_from: range.from, date_to: range.to, push_to_data_core: true
      }).then(function (r) {
        setRows(r.rows || []);
        setDcInfo(r.data_core ? { ok: true, batch: r.data_core.batch_id, count: r.data_core.row_count }
                           : { ok: false, error: r.data_core_error || "未推送" });
        message.success("已取回 " + (r.rows || []).length + " 行");
      }).catch(function (e) { message.error(e.message); })
        .finally(function () { setLoading(false); });
    }

    var stat = function (label, value, color) {
      return h("div", { style: { background: "#fff", border: "1px solid #e8edf4", borderRadius: 10, padding: "12px 16px", minWidth: 120 } },
        h("div", { style: { fontSize: 12, color: "#667085" } }, label),
        h("div", { style: { fontSize: 20, fontWeight: 700, color: color || "#182640", marginTop: 2 } }, value));
    };

    var inputStyle = { padding: "8px 10px", fontSize: 13, border: "1px solid #d6dee8", borderRadius: 6, width: "100%", boxSizing: "border-box" };

    return h("div", { style: { padding: 24, background: "#f7f8fa", minHeight: "100%", fontFamily: FONT } },
      h("div", { style: { maxWidth: 1240, margin: "0 auto" } },
        h("div", { style: { display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 16 } },
          h("div", null,
            h("h2", { style: { margin: "0 0 4px" } }, "🔌 用友畅捷通连接中心"),
            h("p", { style: { color: "#667085", margin: 0 } }, "配置 T+/好会计 开放凭据 → 连通测试 → 一键取数并写入统一数据中心，供智能体问数")),
          h(antd.Button, { href: "https://open.chanjet.com/docs/file/apiFile/tcloud", target: "_blank" }, "开放平台文档")
        ),
        h("div", { style: { display: "flex", gap: 12, flexWrap: "wrap", marginBottom: 16 } },
          stat("凭据状态", cred.configured || cred.app_key ? "已配置" : "未配置", cred.configured || cred.app_key ? "#0e9f6e" : "#c2570a"),
          stat("连通测试", testResult ? (testResult.ok ? "通过" : "失败") : "未测试", testResult ? (testResult.ok ? "#0e9f6e" : "#d92d20") : "#64748b"),
          stat("本次取回行数", String(rows.length), "#1f5ed6"),
          stat("写入数据中心", dcInfo ? (dcInfo.ok ? "批次 " + String(dcInfo.batch || "").slice(0, 12) : "失败") : "—", dcInfo ? (dcInfo.ok ? "#0e9f6e" : "#d92d20") : "#64748b")
        ),
        h("div", { style: { display: "grid", gridTemplateColumns: "minmax(320px, 420px) minmax(0, 1fr)", gap: 16, alignItems: "start" } },
          h("div", { style: { background: "#fff", border: "1px solid #e8edf4", borderRadius: 10, padding: 16 } },
            h("div", { style: { fontWeight: 700, marginBottom: 10 } }, "连接配置"),
            h("div", { style: { display: "flex", flexDirection: "column", gap: 10 } },
              h("label", { style: { fontSize: 12, fontWeight: 600, color: "#344054" } }, "appKey",
                h("input", { value: cred.app_key, onChange: function (e) { setCred(Object.assign({}, cred, { app_key: e.target.value })); }, placeholder: cred.app_key_masked || "开放平台 appKey", style: inputStyle })),
              h("label", { style: { fontSize: 12, fontWeight: 600, color: "#344054" } }, "appSecret",
                h("input", { type: "password", value: cred.app_secret, onChange: function (e) { setCred(Object.assign({}, cred, { app_secret: e.target.value })); }, placeholder: cred.configured ? "已保存（输入新值可覆盖）" : "开放平台 appSecret", style: inputStyle })),
              h("label", { style: { fontSize: 12, fontWeight: 600, color: "#344054" } }, "openToken",
                h("input", { type: "password", value: cred.open_token, onChange: function (e) { setCred(Object.assign({}, cred, { open_token: e.target.value })); }, placeholder: cred.configured ? "已保存（输入新值可覆盖）" : "openToken（有效期 6 天）", style: inputStyle })),
              h("label", { style: { fontSize: 12, fontWeight: 600, color: "#344054" } }, "API 根地址（专属云可改）",
                h("input", { value: cred.api_root, onChange: function (e) { setCred(Object.assign({}, cred, { api_root: e.target.value })); }, style: inputStyle })),
              h("div", { style: { display: "flex", gap: 8 } },
                h(antd.Button, { type: "primary", loading: busy === "save", onClick: saveCred }, "保存凭据"),
                h(antd.Button, { loading: busy === "test", onClick: testConn }, "连通测试")
              ),
              testResult ? h(antd.Alert, { type: testResult.ok ? "success" : "error", showIcon: true,
                message: testResult.ok ? "连通成功，可正常取数" : ("连通失败：" + (testResult.error || "").slice(0, 120)) }) : null
            )
          ),
          h("div", { style: { background: "#fff", border: "1px solid #e8edf4", borderRadius: 10, padding: 16 } },
            h("div", { style: { fontWeight: 700, marginBottom: 10 } }, "取数（T+ 单据列表）"),
            h("div", { style: { display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 10, alignItems: "center" } },
              h(antd.Select, { style: { width: 180 }, value: entity, options: ENTITY_OPTIONS, onChange: setEntity }),
              h(antd.Input, { size: "small", style: { width: 130 }, placeholder: "开始日期", value: range.from, onChange: function (e) { setRange(Object.assign({}, range, { from: e.target.value })); } }),
              h("span", { style: { color: "#98a2b3" } }, "→"),
              h(antd.Input, { size: "small", style: { width: 130 }, placeholder: "结束日期", value: range.to, onChange: function (e) { setRange(Object.assign({}, range, { to: e.target.value })); } }),
              h(antd.Button, { type: "primary", loading: loading, onClick: fetchData }, "取数并写入数据中心")
            ),
            dcInfo ? h(antd.Alert, { style: { marginBottom: 10 }, type: dcInfo.ok ? "success" : "warning", showIcon: true,
              message: dcInfo.ok ? "已写入统一数据中心（正式批次，Data Studio 可读，智能体可问数）"
                                 : ("写入数据中心未成功：" + dcInfo.error) }) : null,
            h(antd.Table, { rowKey: function (r, i) { return "r" + i; }, size: "small", loading: loading,
              pagination: { pageSize: 10 }, columns: COLUMNS, dataSource: rows,
              locale: { emptyText: "配置凭据并点击「取数并写入数据中心」后显示" }, scroll: { x: 700 } })
          )
        )
      )
    );
  }

  Q.registerRoutes("zhiyun-chanjet-hub", [{ path: "/apps/zhiyun-chanjet-hub", component: ChanjetHub, label: "畅捷通连接中心", icon: "🔌", priority: 60 }]);
})();
