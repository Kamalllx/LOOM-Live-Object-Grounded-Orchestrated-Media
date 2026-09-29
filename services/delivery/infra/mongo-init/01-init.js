// Runs once, the first time the mongo volume is created.
// Creates the two collections the delivery service uses and their indexes.
db = db.getSiblingDB("loom");

db.createCollection("learner_memory");
db.createCollection("session_logs");

// One document per learner — the mastery graph lives inside it.
db.learner_memory.createIndex({ learner_id: 1 }, { unique: true });

// One document per session. Re-posting the same session replaces it rather
// than duplicating, which matters when you demo the same cut twice.
db.session_logs.createIndex({ session_id: 1 }, { unique: true });
db.session_logs.createIndex({ learner_id: 1, received_at: -1 });

print("[loom] initialised collections: learner_memory, session_logs");
