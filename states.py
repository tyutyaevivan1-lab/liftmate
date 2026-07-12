"""FSM-состояния для диалога о тренировках."""

from aiogram.fsm.state import State, StatesGroup


class WorkoutStates(StatesGroup):
    """Состояния диалога о тренировках."""

    # Бот ждёт от пользователя недостающие данные о подходе (вес, повторения, подходы)
    waiting_for_details = State()

    # Бот ждёт текстовое название упражнения после нажатия "Добавить своё упражнение"
    waiting_for_custom_name = State()
