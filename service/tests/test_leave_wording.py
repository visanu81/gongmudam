""""Which leave do I use" is understood without the word 휴가, and other 복무 questions keep their routes."""
import unittest

from app import leave_situations as leave


class LeaveWordingTest(unittest.TestCase):
    def test_a_child_or_family_illness_asking_what_to_use_is_family_care(self):
        for q in ('아이가 아파서 복무 중 어떤걸 써야할까', '아이가 아픈데 어떤 휴가를 써야할까', '아이가 아파서 어떤걸 써야할까',
                  '아이가 아파서 복무 뭐 써야 해?', '부모님이 아프셔서 복무 뭐 써?', '아이 학교 상담 가는데 복무 뭘로 해?'):
            with self.subTest(q=q):
                self.assertTrue(leave.family_care(q))
                self.assertFalse(leave.self_sick(q))

    def test_ones_own_illness_asking_what_to_use_is_not_family_care(self):
        for q in ('아파서 복무 중 뭐 써야 해?', '내가 아파서 복무 뭐 올려야 해?', '독감 걸렸는데 복무 뭘로 해?'):
            with self.subTest(q=q):
                self.assertTrue(leave.self_sick(q))
                self.assertFalse(leave.family_care(q))

    def test_other_questions_are_not_taken_as_choosing_leave(self):
        for q in ('복무 의무 뭐 있어?', '복무 규정 어디서 봐?', '근무상황 어떻게 올려?', '아이가 아파서 병원비 뭐 써?', '복무 위반하면 어떻게 돼?'):
            with self.subTest(q=q):
                compact = q.replace(' ', '')
                self.assertFalse(leave.asks_which_leave(compact))
                self.assertFalse(leave.family_care(q))
                self.assertFalse(leave.self_sick(q))


if __name__ == '__main__':
    unittest.main()
