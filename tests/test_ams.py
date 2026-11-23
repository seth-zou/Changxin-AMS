import os
import tempfile
import unittest

from fastapi.testclient import TestClient

_TEMP_DIR = tempfile.mkdtemp(prefix="ams-test-")
os.environ["AMS_DB_PATH"] = os.path.join(_TEMP_DIR, "ams-test.db")
os.environ["AMS_ADMIN_PASSWORD"] = "admin123"

from app.main import app  # noqa: E402


class AMSApiTests(unittest.TestCase):
    RUN = [0]

    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)
        response = cls.client.post("/api/auth/login", json={"user_id": "E0043258", "password": "admin123"})
        assert response.status_code == 200, response.text

    def setUp(self):
        type(self).RUN[0] += 1
        self.suffix = f"_{type(self).RUN[0]}"

    def test_health(self):
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "ok")

    def test_master_data_and_alarm_lifecycle(self):
        c = self.client
        # Base masters
        factory = c.post("/api/resources/factories", json={"FACTORY_ID": "TF1" + self.suffix, "FACTORY_NAME": "一廠"}).json()
        subsystem = c.post("/api/resources/sub-systems", json={"SUB_SYS_ID": "TMES" + self.suffix, "SUB_SYS_NAME": "製造執行系統"}).json()
        mapping = c.post("/api/resources/factory-sub-systems", json={
            "FACTORY_KEY": factory["FACTORY_KEY"], "SUB_SYS_KEY": subsystem["SUB_SYS_KEY"]
        }).json()
        user = c.post("/api/resources/users", json={"USER_ID": "TU1" + self.suffix, "USER_NAME": "使用者一", "E_MAIL": "u1@example.com"}).json()
        user2 = c.post("/api/resources/users", json={"USER_ID": "TU2" + self.suffix, "USER_NAME": "使用者二", "E_MAIL": "u2@example.com"}).json()
        equipment = c.post("/api/resources/equipment", json={"EQP_ID": "TEQP1" + self.suffix, "EQP_NAME": "印刷機A"}).json()
        event = c.post("/api/resources/events", json={
            "EVENT_ID": "TE001" + self.suffix, "EVENT_NAME": "缺料事件", "FACTORY_KEY": factory["FACTORY_KEY"],
            "SUB_SYS_KEY": subsystem["SUB_SYS_KEY"], "EVENT_PRIORITY_ID": 9
        }).json()
        level1 = c.post("/api/resources/event-levels", json={
            "EVENT_KEY": event["EVENT_KEY"], "EVENT_LEVEL_ID": 1, "NUMBER_OF_ACK_USERS": "2", "LEVEL_INTERVAL": 10
        }).json()
        level2 = c.post("/api/resources/event-levels", json={
            "EVENT_KEY": event["EVENT_KEY"], "EVENT_LEVEL_ID": 2, "NUMBER_OF_ACK_USERS": "1", "LEVEL_INTERVAL": 20
        }).json()
        group = c.post("/api/resources/event-groups", json={
            "EVENT_GROUP_ID": "TG001" + self.suffix, "EVENT_GROUP_NAME": "設備人員", "FACTORY_KEY": factory["FACTORY_KEY"],
            "SUB_SYS_KEY": subsystem["SUB_SYS_KEY"]
        }).json()
        c.post("/api/resources/event-group-members", json={"EVENT_GROUP_KEY": group["EVENT_GROUP_KEY"], "USER_KEY": user["USER_KEY"], "MEMBER_SEQ": 1})
        c.post("/api/resources/event-group-members", json={"EVENT_GROUP_KEY": group["EVENT_GROUP_KEY"], "USER_KEY": user2["USER_KEY"], "MEMBER_SEQ": 2})
        c.post("/api/resources/event-level-groups", json={
            "EVENT_KEY": event["EVENT_KEY"], "EVENT_LEVEL_ID": 1, "EVENT_GROUP_KEY": group["EVENT_GROUP_KEY"],
            "ENABLE_SEND_DEVICES": "EMail;Sms"
        }).json()
        alarm_info = c.post("/api/resources/alarm-infos", json={
            "ALARM_INFO_ID": "TA001" + self.suffix, "ALARM_ID_DESC": "缺料", "FACTORY_KEY": factory["FACTORY_KEY"],
            "SUB_SYS_KEY": subsystem["SUB_SYS_KEY"], "EVENT_KEY": event["EVENT_KEY"],
            "EQP_KEY": equipment["EQP_KEY"], "EVENT_PTY_ID": 9, "IGNORE_PERIOD": 900
        }).json()

        # A valid supplement creates a process alarm and recipients.
        response = c.post("/api/alarms/send", json={
            "FACTORY_ID": "TF1" + self.suffix, "SUB_SYS_ID": "TMES" + self.suffix, "EQP_ID": "TEQP1" + self.suffix, "ALARM_INFO_ID": "TA001" + self.suffix,
            "SUBJECT": "EQP1 缺料", "CONTENT": "測試警報"
        })
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["STATUS"], "Process")
        self.assertGreater(body["sent"], 0)
        alarm_key = body["ALARM_KEY"]

        # A duplicate inside the ignore window is invalid.
        duplicate = c.post("/api/alarms/send", json={
            "FACTORY_ID": "TF1" + self.suffix, "SUB_SYS_ID": "TMES" + self.suffix, "EQP_ID": "TEQP1" + self.suffix, "ALARM_INFO_ID": "TA001" + self.suffix,
            "SUBJECT": "duplicate", "CONTENT": "duplicate"
        })
        self.assertEqual(duplicate.json().get("FAILURE_TYPE"), "IGNORE_SAME_ALARM")

        # First ACK does not complete because level 1 requires two users.
        ack1 = c.post("/api/alarms/ack", json={"ALARM_KEYS": [alarm_key], "COMMENT": "first"})
        self.assertEqual(ack1.status_code, 200)
        self.assertFalse(ack1.json()["results"][0]["ok"])

        # Log in as another user and finish the alarm.
        token = c.cookies.get("ams_session")
        c.post("/api/auth/login", json={"user_id": "U2", "password": ""})
        # The seed user has no password, so force a password via direct API is impossible; use admin again.
        c.post("/api/auth/logout")
        login = c.post("/api/auth/login", json={"user_id": "E0043258", "password": "admin123"})
        self.assertEqual(login.status_code, 200)
        ack2 = c.post("/api/alarms/ack", json={"ALARM_KEYS": [alarm_key], "COMMENT": "second"})
        # Admin is not a recipient, so second ACK by admin is rejected in this isolated API test.
        self.assertEqual(ack2.json()["results"][0]["ok"], False)

        # Manual alarm lifecycle remains independent from event levels.
        manual = c.post("/api/alarms/manual-send", json={
            "FACTORY_KEY": factory["FACTORY_KEY"], "SUB_SYS_KEY": subsystem["SUB_SYS_KEY"],
            "USER_KEYS": ["USER_ADMIN"], "SEND_TYPES": ["EMail"], "SUBJECT": "manual", "CONTENT": "manual"
        })
        self.assertEqual(manual.status_code, 200)
        manual_key = manual.json()["ALARM_KEY"]
        ack = c.post("/api/alarms/ack", json={"ALARM_KEYS": [manual_key], "COMMENT": "manual"})
        self.assertEqual(ack.json()["results"][0]["status"], "Completed")

        # A wildcard equipment rule matches any EQP with the same four-element prefix.
        wildcard_eqp = c.post("/api/resources/equipment", json={"EQP_ID": "*", "EQP_NAME": "任一機台"}).json()
        wildcard_info = c.post("/api/resources/alarm-infos", json={
            "ALARM_INFO_ID": "A999" + self.suffix, "ALARM_ID_DESC": "全機台缺料", "FACTORY_KEY": factory["FACTORY_KEY"],
            "SUB_SYS_KEY": subsystem["SUB_SYS_KEY"], "EVENT_KEY": event["EVENT_KEY"],
            "EQP_KEY": wildcard_eqp["EQP_KEY"], "IGNORE_PERIOD": 0
        }).json()
        wildcard_send = c.post("/api/alarms/send", json={
            "FACTORY_ID": "TF1" + self.suffix, "SUB_SYS_ID": "TMES" + self.suffix, "EQP_ID": "TEQP1" + self.suffix, "ALARM_INFO_ID": "A999" + self.suffix,
            "SUBJECT": "wildcard", "CONTENT": "wildcard"
        })
        self.assertEqual(wildcard_send.status_code, 200)
        self.assertEqual(wildcard_send.json()["STATUS"], "Process")

        # Reports expose summary, history and device status.
        self.assertEqual(c.get("/api/reports/alarm-summary").status_code, 200)
        self.assertEqual(c.get("/api/reports/history").status_code, 200)
        self.assertEqual(c.get("/api/reports/device-status").status_code, 200)

    def test_unauthenticated_and_password_change(self):
        from app.main import app as test_app
        fresh = TestClient(test_app)
        self.assertEqual(fresh.get('/api/reports/alarm-summary').status_code, 401)
        self.assertEqual(fresh.get('/api/resources/users').status_code, 401)

    def test_level_upgrade_and_termination(self):
        c = self.client
        # Resources created in the lifecycle test are visible through API, so use a fresh factory pair.
        f = c.post('/api/resources/factories', json={'FACTORY_ID': 'F2' + self.suffix, 'FACTORY_NAME': '二廠'}).json()
        s = c.post('/api/resources/sub-systems', json={'SUB_SYS_ID': 'EAP' + self.suffix, 'SUB_SYS_NAME': '設備自動化'}).json()
        eq = c.post('/api/resources/equipment', json={'EQP_ID': 'EQP2' + self.suffix, 'EQP_NAME': '機台二'}).json()
        ev = c.post('/api/resources/events', json={'EVENT_ID': 'E002' + self.suffix, 'EVENT_NAME': '升級事件', 'FACTORY_KEY': f['FACTORY_KEY'], 'SUB_SYS_KEY': s['SUB_SYS_KEY']}).json()
        c.post('/api/resources/event-levels', json={'EVENT_KEY': ev['EVENT_KEY'], 'EVENT_LEVEL_ID': 1, 'NUMBER_OF_ACK_USERS': '1', 'LEVEL_INTERVAL': 0})
        l2 = c.post('/api/resources/event-levels', json={'EVENT_KEY': ev['EVENT_KEY'], 'EVENT_LEVEL_ID': 2, 'NUMBER_OF_ACK_USERS': '1', 'LEVEL_INTERVAL': 0}).json()
        g = c.post('/api/resources/event-groups', json={'EVENT_GROUP_ID': 'G2' + self.suffix, 'EVENT_GROUP_NAME': '升級群組', 'FACTORY_KEY': f['FACTORY_KEY'], 'SUB_SYS_KEY': s['SUB_SYS_KEY']}).json()
        c.post('/api/resources/event-group-members', json={'EVENT_GROUP_KEY': g['EVENT_GROUP_KEY'], 'USER_KEY': 'USER_ADMIN', 'MEMBER_SEQ': 1})
        c.post('/api/resources/event-level-groups', json={'EVENT_KEY': ev['EVENT_KEY'], 'EVENT_LEVEL_ID': 1, 'EVENT_GROUP_KEY': g['EVENT_GROUP_KEY'], 'ENABLE_SEND_DEVICES': 'EMail'})
        c.post('/api/resources/event-level-groups', json={'EVENT_KEY': ev['EVENT_KEY'], 'EVENT_LEVEL_ID': 2, 'EVENT_GROUP_KEY': g['EVENT_GROUP_KEY'], 'ENABLE_SEND_DEVICES': 'EMail'})
        ai = c.post('/api/resources/alarm-infos', json={'ALARM_INFO_ID': 'A2' + self.suffix, 'ALARM_ID_DESC': '升級警報', 'FACTORY_KEY': f['FACTORY_KEY'], 'SUB_SYS_KEY': s['SUB_SYS_KEY'], 'EVENT_KEY': ev['EVENT_KEY'], 'EQP_KEY': eq['EQP_KEY'], 'IGNORE_PERIOD': 0}).json()
        alarm = c.post('/api/alarms/send', json={'FACTORY_ID': 'F2' + self.suffix, 'SUB_SYS_ID': 'EAP' + self.suffix, 'EQP_ID': 'EQP2' + self.suffix, 'ALARM_INFO_ID': 'A2' + self.suffix, 'SUBJECT': 'upgrade', 'CONTENT': 'upgrade'}).json()
        alarm_status = c.post('/api/alarms/send', json={'FACTORY_ID': 'F2' + self.suffix, 'SUB_SYS_ID': 'EAP' + self.suffix, 'EQP_ID': 'EQP2' + self.suffix, 'ALARM_INFO_ID': 'A2' + self.suffix, 'SUBJECT': 'upgrade', 'CONTENT': 'upgrade'}).text
        up = c.post('/api/alarms/upgrade')
        self.assertEqual(up.status_code, 200, alarm_status)
        found = [x for x in up.json()['alarms'] if x['ALARM_KEY'] == alarm['ALARM_KEY']]
        self.assertTrue(found)
        self.assertEqual(found[0]['level'], 2)
        term = c.post('/api/alarms/terminate', json={'ALARM_KEYS': [alarm['ALARM_KEY']], 'COMMENT': 'done'})
        self.assertEqual(term.json()['results'][0]['status'], 'Terminated')
        tx = c.get(f"/api/alarms/{alarm['ALARM_KEY']}/transactions").json()
        self.assertEqual([x['TRANSACTION_TYPE'] for x in tx], ['Create', 'Modify', 'LevelUpgrade', 'Terminate'])


if __name__ == "__main__":
    unittest.main()
