class UserRepo:
    def lookup(self, key):
        return {"user": key}


class OrderRepo:
    def lookup(self, key):
        return {"order": key}


def find(repo, key):
    return repo.lookup(key)
