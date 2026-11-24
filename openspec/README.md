# OpenSpec в Sber MQTT Bridge

OpenSpec хранит требования к поведению и планы изменений рядом с кодом.
Описание каждой области появляется при реальной работе над ней.

- `specs/` — принятые требования к поведению.
- `changes/<change>/` — предложение, изменения требований, дизайн и задачи.
- `changes/archive/` — завершённые изменения и причины решений.
- `config.yaml` — контекст и правила подготовки артефактов.

Для воспроизводимости используется CLI **1.16.0**, Node.js >=22.12.0:

```bash
npx --yes @fission-ai/openspec@1.16.0 list --json
npx --yes @fission-ai/openspec@1.16.0 status --change <change> --json
npx --yes @fission-ai/openspec@1.16.0 validate --all --strict
```

CLI запускается через npx; зависимости Python и runtime интеграции не меняются.
При обновлении CLI выбрать версию осознанно и проверить сгенерированные инструкции.

Для Codex установлены project skills в `.agents/skills/`: `openspec-propose`,
`openspec-apply-change`, `openspec-update-change`, `openspec-sync-specs`,
`openspec-archive-change`, `openspec-explore`. Для Claude Code установлены
локальные команды `/opsx:propose`, `/opsx:apply`, `/opsx:update`, `/opsx:sync`,
`/opsx:archive`, `/opsx:explore`. Новый сеанс может потребоваться для обнаружения
добавленных skills и команд.

Обычный цикл: изучить issue и код → подготовить change → проверить требования
и сценарии → реализовать и проверить → архивировать. `tasks.md` является
планом выполнения этого изменения; прежние планы используются как источники.
Валидация OpenSpec проверяет артефакты и не заменяет тесты интеграции.

Спецификации и изменения предназначены для Git. Личная память `.codex/`,
локальные инструкции и исходные журналы Claude остаются локальными.
В артефактах указывать ссылки на issues/PR и необходимые наблюдения;
учётные данные и личные выгрузки туда не переносить.

Документация: [работа с существующим проектом](https://github.com/Fission-AI/OpenSpec/blob/main/docs/existing-projects.md),
[концепции](https://github.com/Fission-AI/OpenSpec/blob/main/docs/concepts.md).
