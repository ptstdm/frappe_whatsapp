import random
import time

import frappe


def run_with_deadlock_retry(
	op,
	*,
	attempts=5,
	backoff_base=0.5,
	exceptions=(
		frappe.QueryDeadlockError,
		frappe.QueryTimeoutError,
	),
	on_retry=None,
	on_exhausted="raise",
	on_deadlock_exhausted=None,
	on_error=None,
	log_title=None,
	log_context=None,
):
	"""
	Run an operation with rollback + retry for transient DB conflicts.

	Args:
		op: Callable to execute.
		attempts: Maximum retry attempts.
		backoff_base: Base delay for exponential backoff.
		exceptions: Exception tuple that should trigger retry.
		on_retry: Callback executed after rollback before retry.
		on_exhausted:
			- "raise": re-raise final exception.
			- "log": log and return None.
		on_deadlock_exhausted: Callback executed when retry limit is exhausted.
		on_error: Callback executed for non-lock exceptions.
		log_title: Error log title.
		log_context: Additional context for error log.
	"""

	for attempt in range(attempts):
		try:
			return op()

		except exceptions:
			frappe.db.rollback()

			if attempt == attempts - 1:
				if log_title:
					frappe.log_error(
						title=log_title,
						message=f"{log_context} (deadlock after {attempt + 1} attempts)\n{frappe.get_traceback()}",
					)

				if on_deadlock_exhausted:
					return on_deadlock_exhausted()

				if on_exhausted == "raise":
					raise

				return None

			if on_retry:
				on_retry(attempt)

			if not frappe.local.flags.in_test:
				time.sleep(
					random.uniform(
						0,
						backoff_base * (2**attempt),
					)
				)

		except Exception as e:
			frappe.db.rollback()

			if log_title:
				frappe.log_error(
					title=log_title,
					message=f"{log_context}\nError: {e!s}\n{frappe.get_traceback()}",
				)

			if on_error:
				return on_error(e)

			if on_exhausted == "raise":
				raise

			return None