#клава для бота(снизу)
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import ReplyKeyboardBuilder

def get_keyboard(
    *btns: str,
    placeholder: str = None,
    request_contact: int = None,
    request_location: int = None,
    sizes: tuple[int] = (2,),
):
    '''
    Parameters request_contact and request_location must be as indexes of btns args for buttons you need.
    Example:
    get_keyboard(
            "Меню",
            "О магазине",
            "Варианты оплаты",
            "Варианты доставки",
            "Отправить номер телефона"
            placeholder="Что вас интересует?",
            request_contact=4,
            sizes=(2, 2, 1)
        )
    '''
    keyboard = ReplyKeyboardBuilder()

    for index, text in enumerate(btns, start=0):
        
        if request_contact is not None and request_contact == index:
            keyboard.add(KeyboardButton(text=text, request_contact=True))

        elif request_location is not None and request_location == index:
            keyboard.add(KeyboardButton(text=text, request_location=True))
        else:

            keyboard.add(KeyboardButton(text=text))

    return keyboard.adjust(*sizes).as_markup(
            resize_keyboard=True, input_field_placeholder=placeholder)




'''inline_btn1 = InlineKeyboardButton(text="Отзывы", url="https://web.telegram.org/k/#@Wardrobe_Express")
inline_btn2 = InlineKeyboardButton(text="Поддержка", url="https://web.telegram.org/k/#@NckGv")
    #inline_keyboard.add(InlineKeyboardButton(text="Поддержка", url="https://web.telegram.org/k/#@NckGv"))
    #await message.answer("Наша поддержка и отзывы: ", reply_markup=inline_keyboard)
inline_keyboard = InlineKeyboardMarkup().add(inline_btn1, inline_btn2)'''
