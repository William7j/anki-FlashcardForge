from flashforge.app import acquire_instance_lock


def test_instance_lock_rejects_a_second_process_slot(tmp_path) -> None:
    lock_path = tmp_path / "FlashForge-instance.lock"
    first = acquire_instance_lock(lock_path)

    assert first is not None
    assert acquire_instance_lock(lock_path) is None

    first.unlock()
    replacement = acquire_instance_lock(lock_path)
    assert replacement is not None
    replacement.unlock()
