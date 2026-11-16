"""
Unity の CompactionProbe が /sim/compaction_probe に送る記録を CSV に保存する

メッセージ（std_msgs/String, JSON）:
  {"request_id": …, "episode_name": …, "final": false,
   "header": "sim_time,phase,…,c_z5",     列名（毎回同じものが届く）
   "rows": "…\n…\n"}                      1回分の記録（CSV の行。改行で終わる）
  final が true のメッセージが、そのエピソードの最後の記録（phase が done になった時点）。

保存する CSV の列は、これまで Unity 側が書き出していたファイルと同じ。
setup の request_id と一致するメッセージだけを保存するので、前のエピソードの記録は混ざらない。
"""
import json
import threading


class CompactionRecorder:
    def __init__(self, iface):
        self.lock = threading.Lock()
        self.active = False
        self.final = threading.Event()
        iface.probe_listeners.append(self._on_probe)

    def start(self, path, request_id):
        with self.lock:
            self.path = path
            self.request_id = request_id
            self.file = open(path, "w", newline="", encoding="utf-8")
            self.header_written = False
            self.snapshots = 0
            self.rows = 0
            self.final.clear()
            self.active = True

    def _on_probe(self, data):
        try:
            msg = json.loads(data)
        except ValueError:
            return
        with self.lock:
            if not self.active or msg.get("request_id") != self.request_id:
                return
            if not self.header_written:
                self.file.write(msg["header"] + "\n")
                self.header_written = True
            rows = msg.get("rows", "")
            self.file.write(rows)
            self.file.flush()
            self.rows += rows.count("\n")
            self.snapshots += 1
            if msg.get("final"):
                self.final.set()

    def finish(self, timeout=3.0):
        """最後の記録（final）を最大 timeout 秒待ってから閉じる。timeout=0 なら待たずに閉じる"""
        if not self.active:
            return {}
        got_final = self.final.wait(timeout) if timeout > 0 else self.final.is_set()
        with self.lock:
            self.active = False
            self.file.close()
        if not got_final:
            print(f"注意: 締固めの最後の記録が届きませんでした（{self.path}）")
        return {"compaction_path": self.path, "compaction_snapshots": self.snapshots,
                "compaction_rows": self.rows, "compaction_final": got_final}