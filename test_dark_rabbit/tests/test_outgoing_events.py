from odoo.tests.common import RecordCapturer, TransactionCase


class TestFlightEventProcessor(TransactionCase):
    def setUp(self):
        super().setUp()

        self.local_conn = self.env["dark.rabbit.connection"].create(
            {
                "name": "DemoLocalConn",
                "code": "demo-local-conn",
                "host": "localhost",
                "port": 5672,
                "user": "dark.rabbit",
                "password": "dark.rabbit",
            }
        )
        self.exchange_out_all = self.env["dark.rabbit.exchange"].create(
            {
                "connection_id": self.local_conn.id,
                "name": "test.dark.rabbit.outgoing.all",
            }
        )
        self.exchange_out_d1 = self.env["dark.rabbit.exchange"].create(
            {
                "connection_id": self.local_conn.id,
                "name": "test.dark.rabbit.outgoing.d1",
            }
        )
        self.exchange_out_d2 = self.env["dark.rabbit.exchange"].create(
            {
                "connection_id": self.local_conn.id,
                "name": "test.dark.rabbit.outgoing.d2",
            }
        )
        self.tag_1 = self.env["dark.rabbit.outgoing.routing.tag"].create(
            {
                "name": "D1",
                "code": "d1",
            }
        )
        self.tag_2 = self.env["dark.rabbit.outgoing.routing.tag"].create(
            {
                "name": "D2",
                "code": "d2",
            }
        )
        self.env["dark.rabbit.outgoing.routing"].create(
            [
                {
                    "connection_id": self.local_conn.id,
                    "outgoing_event_type_id": self.env.ref(
                        "test_dark_rabbit.outgoing_event_type_created"
                    ).id,
                    "exchange_id": self.exchange_out_all.id,
                    "routing_key": "all",
                },
                {
                    "connection_id": self.local_conn.id,
                    "outgoing_event_type_id": self.env.ref(
                        "test_dark_rabbit.outgoing_event_type_created"
                    ).id,
                    "require_tag_id": self.tag_1.id,
                    "exchange_id": self.exchange_out_d1.id,
                    "routing_key": "d1",
                },
                {
                    "connection_id": self.local_conn.id,
                    "outgoing_event_type_id": self.env.ref(
                        "test_dark_rabbit.outgoing_event_type_created"
                    ).id,
                    "require_tag_id": self.tag_2.id,
                    "exchange_id": self.exchange_out_d2.id,
                    "routing_key": "d2",
                },
            ]
        )

    def test_send_tags_1(self):
        with RecordCapturer(self.env["dark.rabbit.outgoing.event"], []) as c:
            self.env["test.dark.rabbit.outgoing.event"].create(
                {
                    "body": "Test",
                }
            )

        self.assertRecordValues(
            c.records,
            [
                {
                    "exchange": "test.dark.rabbit.outgoing.all",
                    "body": """{"body": "Test"}""",
                }
            ],
        )

        with RecordCapturer(self.env["dark.rabbit.outgoing.event"], []) as c:
            self.env["test.dark.rabbit.outgoing.event"].create(
                {
                    "body": "Test",
                    "tag_id": self.tag_1.id,
                }
            )

        self.assertRecordValues(
            c.records,
            [
                {
                    "exchange": "test.dark.rabbit.outgoing.all",
                    "body": """{"body": "Test"}""",
                },
                {
                    "exchange": "test.dark.rabbit.outgoing.d1",
                    "body": """{"body": "Test"}""",
                },
            ],
        )

        with RecordCapturer(self.env["dark.rabbit.outgoing.event"], []) as c:
            self.env["test.dark.rabbit.outgoing.event"].create(
                {
                    "body": "Test",
                    "tag_id": self.tag_2.id,
                }
            )

        self.assertRecordValues(
            c.records,
            [
                {
                    "exchange": "test.dark.rabbit.outgoing.all",
                    "body": """{"body": "Test"}""",
                },
                {
                    "exchange": "test.dark.rabbit.outgoing.d2",
                    "body": """{"body": "Test"}""",
                },
            ],
        )
