"""Cursor pagination for ``GET /v1/transactions``."""

from __future__ import annotations

from typing import (
    Any,
    AsyncIterator,
    Awaitable,
    Callable,
    Iterator,
    List,
    Optional,
)

from ._types import Transaction, TransactionListResponse

__all__ = ["PAGE_SIZE", "TransactionPage", "AsyncTransactionPage"]

#: Fixed page size of ``GET /v1/transactions``.
PAGE_SIZE = 10


class TransactionPage:
    """One page of transactions, plus the means to walk the rest.

    Iterating the page walks every remaining transaction across every following
    page, fetching lazily::

        for transaction in epay.transactions.list(status="completed"):
            print(transaction["reference"])

    Use :attr:`data` instead when you want exactly the current page.
    """

    def __init__(
        self,
        response: TransactionListResponse,
        fetch_next: Callable[[str], TransactionPage],
    ) -> None:
        payload: Any = response or {}
        #: Up to 10 transactions, newest first.
        self.data: List[Transaction] = payload.get("data") or []
        #: Cursor for the next page, or ``None`` on the last page.
        self.next_cursor: Optional[str] = payload.get("nextCursor")
        #: Whether more transactions exist beyond this page.
        self.has_more: bool = bool(payload.get("hasMore"))
        self._fetch_next = fetch_next

    def next_page(self) -> Optional[TransactionPage]:
        """Fetches the next page, or returns ``None`` on the last page."""
        if not self.has_more or not self.next_cursor:
            return None
        return self._fetch_next(self.next_cursor)

    def pages(self) -> Iterator[TransactionPage]:
        """Yields this page and each following page in turn."""
        page: Optional[TransactionPage] = self
        while page is not None:
            yield page
            page = page.next_page()

    def __iter__(self) -> Iterator[Transaction]:
        """Yields every transaction from this page onward, fetching on demand."""
        for page in self.pages():
            yield from page.data

    def to_list(self, limit: Optional[int] = None) -> List[Transaction]:
        """Collects transactions from this page onward into a list.

        Args:
            limit: Stop after this many transactions. Omit to collect
                everything, which for a busy account may be many requests.
        """
        collected: List[Transaction] = []
        for transaction in self:
            collected.append(transaction)
            if limit is not None and len(collected) >= limit:
                break
        return collected

    def __len__(self) -> int:
        """The size of this page only, not the full result set."""
        return len(self.data)

    def __repr__(self) -> str:
        return f"TransactionPage(count={len(self.data)}, has_more={self.has_more})"


class AsyncTransactionPage:
    """One page of transactions for the async client.

    Iterating walks every following page, fetching lazily::

        async for transaction in await epay.transactions.list(status="completed"):
            print(transaction["reference"])
    """

    def __init__(
        self,
        response: TransactionListResponse,
        fetch_next: Callable[[str], Awaitable[AsyncTransactionPage]],
    ) -> None:
        payload: Any = response or {}
        self.data: List[Transaction] = payload.get("data") or []
        self.next_cursor: Optional[str] = payload.get("nextCursor")
        self.has_more: bool = bool(payload.get("hasMore"))
        self._fetch_next = fetch_next

    async def next_page(self) -> Optional[AsyncTransactionPage]:
        """Fetches the next page, or returns ``None`` on the last page."""
        if not self.has_more or not self.next_cursor:
            return None
        return await self._fetch_next(self.next_cursor)

    async def pages(self) -> AsyncIterator[AsyncTransactionPage]:
        """Yields this page and each following page in turn."""
        page: Optional[AsyncTransactionPage] = self
        while page is not None:
            yield page
            page = await page.next_page()

    async def __aiter__(self) -> AsyncIterator[Transaction]:
        """Yields every transaction from this page onward, fetching on demand."""
        async for page in self.pages():
            for transaction in page.data:
                yield transaction

    async def to_list(self, limit: Optional[int] = None) -> List[Transaction]:
        """Collects transactions from this page onward into a list."""
        collected: List[Transaction] = []
        async for transaction in self:
            collected.append(transaction)
            if limit is not None and len(collected) >= limit:
                break
        return collected

    def __len__(self) -> int:
        """The size of this page only, not the full result set."""
        return len(self.data)

    def __repr__(self) -> str:
        return f"AsyncTransactionPage(count={len(self.data)}, has_more={self.has_more})"
