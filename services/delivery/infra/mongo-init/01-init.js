db = db.getSiblingDB("loom");

db.createCollection("learner_memory");
db.createCollection("session_logs");
db.learner_memory.createIndex({ learner_id: 1 }, { unique: true });
db.session_logs.createIndex({ session_id: 1 }, { unique: true });
db.session_logs.createIndex({ learner_id: 1, received_at: -1 });

print("[loom] initialised collections: learner_memory, session_logs");
