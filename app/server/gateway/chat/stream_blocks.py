"""Incrementally hide protocol blocks without retracting already visible prose."""


class BlockStreamFilter:
    def __init__(self, tags):
        self.pending = ""
        self.hidden = False
        self.closing = ""
        self.opening = [f"[{tag}]" for tag in tags]

    def feed(self, chunk: str) -> str:
        self.pending += chunk
        output = ""
        while self.pending:
            markers = [self.closing] if self.hidden else self.opening
            found = [
                (self.pending.find(tag), tag) for tag in markers if tag in self.pending
            ]
            if found:
                index, marker = min(found)
                if not self.hidden:
                    output += self.pending[:index]
                    self.closing = "[/" + marker[1:]
                self.pending = self.pending[index + len(marker):]
                self.hidden = not self.hidden
                continue
            keep = max(
                (n for tag in markers
                 for n in range(1, min(len(tag), len(self.pending) + 1))
                 if tag.startswith(self.pending[-n:])),
                default=0,
            )
            if not self.hidden:
                output += self.pending[:-keep] if keep else self.pending
            self.pending = self.pending[-keep:] if keep else ""
            break
        return output

    def finish(self) -> str:
        # A partial protocol opening/closing tag must not become visible at EOF.
        incomplete = self.hidden or any(tag.startswith(self.pending) for tag in self.opening)
        result = "" if incomplete else self.pending
        self.pending = ""
        return result
