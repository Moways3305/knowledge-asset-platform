import { describe, expect, it } from "vitest";
import { confirmationSubjectLabel } from "./UploadConfirmPanel";

describe("confirmation subject label", () => {
  it("uses 主题 for governed libraries and 标题 for personal intake", () => {
    expect(confirmationSubjectLabel("project")).toBe("主题");
    expect(confirmationSubjectLabel("company")).toBe("主题");
    expect(confirmationSubjectLabel("personal")).toBe("标题");
    expect(confirmationSubjectLabel("")).toBe("标题");
  });
});
