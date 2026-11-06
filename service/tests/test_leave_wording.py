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

    def test_saying_one_is_ill_is_enough(self):
        for q in ('아파서 쉬어야 해요', '몸이 아파서 쉬어야 해요', '아파서 출근 못 해요', '아파서 못 나가요', '오늘 아파서 쉬고 싶어요',
                  '감기 걸려서 쉬어야 해요', '독감 걸렸어요', '독감이라 출근 못 해요', '몸살이 심해서 쉬어야 해요', '다쳐서 출근 못 해요',
                  '수술해야 해서 쉬어야 해요', '입원해야 해요', '입원해서 출근 못 해요', '코로나 걸렸어요', '아파요', '머리가 아파요',
                  '국가공무원인데 아파서 쉬어야 해요', '우울증으로 쉬어야 해요', '공황장애로 출근 못 해요', '정신과 치료로 쉬어야 해요'):
            with self.subTest(q=q):
                self.assertTrue(leave.self_sick(q))
                self.assertFalse(leave.family_care(q))

    def test_a_family_members_illness_is_family_care(self):
        for q in ('아이가 아파서 쉬어야 해요', '아이가 아파서 출근 못 해요', '어머니가 아파서 쉬어야 해요', '배우자가 아파서 쉬어야 해요',
                  '부모님이 입원해서 쉬어야 해요'):
            with self.subTest(q=q):
                self.assertTrue(leave.family_care(q))
                self.assertFalse(leave.self_sick(q))

    def test_other_people_and_other_words_are_not_own_illness(self):
        for q in ('직원이 아파서 쉬어야 한대요', '동료가 아파서 대신 근무해요', '팀원이 입원했어요', '저는 아프지 않지만 근무가 어려워요',
                  '아프지 않은데 쉬고 싶어요', '아픈 건 아닌데 쉬어야 해요', '머리 아픈 업무예요', '아파트 관리비 품의',
                  '아파트 이사 때문에 쉬어야 해요', '아프리카 출장 후 쉬어야 해요', '쉬어야 해요', '쉬고 싶어요', '병원 가야 해요',
                  '아파서 초과근무 못 해요', '아파서 출장 못 가요', '아파서 당직 바꿔야 해요', '아파서 교육 못 가요',
                  '아파서 쉬고 싶은데 연가 써도 되나요', '오래 아파서 쉬어야 하는데 휴직 되나요', '부상자 명단 정리', '수술실 점검', '아이 치료로 쉬어야 해요', '치료비 때문에 쉬어야 해요'):
            with self.subTest(q=q):
                self.assertFalse(leave.self_sick(q))

    def test_other_questions_are_not_taken_as_choosing_leave(self):
        for q in ('복무 의무 뭐 있어?', '복무 규정 어디서 봐?', '근무상황 어떻게 올려?', '아이가 아파서 병원비 뭐 써?', '복무 위반하면 어떻게 돼?'):
            with self.subTest(q=q):
                compact = q.replace(' ', '')
                self.assertFalse(leave.asks_which_leave(compact))
                self.assertFalse(leave.family_care(q))
                self.assertFalse(leave.self_sick(q))


if __name__ == '__main__':
    unittest.main()
