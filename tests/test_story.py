

def test_speed_for_leaves_a_reel_that_fits_alone_and_speeds_up_a_long_one_only_as_much_as_needed():
    from engine.story import speed_for
    short = [5.0] * 6 + [3.0]
    assert speed_for(short, [8] * 6 + [5]) == 1.0                                   # 6 x 8 s + 5 s = 53 s already fits
    long = [8.5] * 6 + [4.0]                                                        # 6 x 9.7 s + 5.2 s = 63.4 s: too long
    f = speed_for(long, [8] * 6 + [5])
    assert 1.0 < f <= 1.25
    assert sum(round(max(m, d / f + 1.2), 2) for d, m in zip(long, [8] * 6 + [5])) <= 59.4
    assert speed_for([20.0] * 7, [8] * 7) == 1.25                                    # hopeless: capped at 1.25x, the Reel is then held back
