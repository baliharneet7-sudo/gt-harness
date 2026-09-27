class Store:
    def save(self, record):
        raise NotImplementedError


class MemoryStore(Store):
    def save(self, record):
        return record


class FileStore(Store):
    def save(self, record):
        return str(record)


def persist(store: Store, record):
    return store.save(record)
